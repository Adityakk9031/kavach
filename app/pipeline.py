"""Per-call pipeline: runs the detector on each final caller turn, in order, off the STT reader's path.

Triggers are published to `on_trigger` callbacks (the family-voice warning in M3, the Telegram alert in M6).
Every timing is logged as an event so latency can be computed from one place.
"""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable

from app.call_room import CallRoom
from app.detector import Decision, Detector

log = logging.getLogger("kavach.pipeline")

TriggerHook = Callable[["CallPipeline", Decision, dict], Awaitable[None]]


class CallPipeline:
    def __init__(self, room: CallRoom, detector: Detector):
        self.room = room
        self.detector = detector
        self.tracker = detector.new_tracker()
        self.history: list[dict] = []  # every final turn, both channels, in order
        self.queue: asyncio.Queue = asyncio.Queue()
        self.on_trigger: list[TriggerHook] = []
        self.on_new_stage: list[TriggerHook] = []
        self.triggered = False
        self.hook_tasks: set[asyncio.Task] = set()
        self.max_risk = 0.0
        self._worker = asyncio.create_task(self._run(), name=f"pipeline-{room.call_id}")
        room.on_final_hooks.append(self.on_final)
        room.on_end_hooks.append(self.close)

    async def on_final(self, room: CallRoom, turn: dict) -> None:
        self.history.append({"channel": turn["channel"], "text": turn["text"], "idx": turn["idx"]})
        if turn["channel"] == "caller":
            await self.queue.put((turn, list(self.history)))

    async def _run(self) -> None:
        while True:
            turn, window = await self.queue.get()
            try:
                await self._analyse(turn, window)
            except Exception:
                log.exception("detection failed for call %s", self.room.call_id)
            finally:
                self.queue.task_done()

    async def _analyse(self, turn: dict, window: list[dict]) -> None:
        room = self.room
        t_start = time.monotonic()
        decision, info = await self.detector.process(self.tracker, window)
        if decision is None:
            room.log_event("detect_error", {"turn_idx": turn["idx"], **info})
            await room.broadcast({"type": "detection", "error": info["error"], "turn_idx": turn["idx"]})
            return
        now = time.monotonic()
        # When the caller actually stopped talking, on the monotonic clock (None if unknown).
        turn_end_at = None
        if turn.get("audio_end_ms") is not None and "caller" in room.clocks:
            turn_end_at = room.clocks["caller"].time_at(turn["audio_end_ms"])
        self.max_risk = max(self.max_risk, decision.risk_cum)
        payload = {
            "turn_idx": turn["idx"], "stages_now": decision.stages_now, "stages_all": decision.stages_all,
            "risk_llm": decision.risk_llm, "risk_cum": decision.risk_cum, "trigger": decision.trigger,
            "reason": decision.reason, "llm_ms": info["llm_ms"], "model": info["model"],
            "queue_wait_ms": round((t_start - turn["final_at"]) * 1000),
            "since_turn_end_ms": round((now - turn_end_at) * 1000) if turn_end_at else None,
        }
        room.log_event("detect", payload, now)
        room.store._exec(
            "INSERT INTO detections(call_id, turn_id, stages, evidence_quotes, risk_llm, risk_cum, rationale, "
            "triggered, llm_ms, model) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (room.call_id, turn["turn_id"], json.dumps(decision.stages_all), json.dumps(info["evidence_quotes"]),
             decision.risk_llm, decision.risk_cum, info["rationale"], int(decision.trigger), info["llm_ms"],
             info["model"]))
        room.store.update_call(room.call_id, max_risk=self.max_risk)
        await room.broadcast({"type": "detection", **payload, "quotes": info["evidence_quotes"],
                              "rationale": info["rationale"]})
        if decision.trigger and not self.triggered:
            self.triggered = True
            trig = {**payload, "turn_end_at": turn_end_at}
            room.log_event("trigger", {k: v for k, v in trig.items() if k != "turn_end_at"}, now)
            for hook in self.on_trigger:
                self._spawn(hook, decision, {**trig, "turn": turn})
        if decision.new_stages:
            for hook in self.on_new_stage:
                self._spawn(hook, decision, {**payload, "turn": turn, "turn_end_at": turn_end_at})

    def _spawn(self, hook: TriggerHook, decision: Decision, info: dict) -> None:
        """Run a trigger hook on its own task. The warning (several seconds of audio) and the family alert must not
        wait for each other, a hook that raises must not stop the others, and later turns must keep being analysed."""
        async def run():
            try:
                await hook(self, decision, info)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("trigger hook %s failed", getattr(hook, "__qualname__", hook))
                self.room.log_event("hook_error", {"hook": getattr(hook, "__qualname__", str(hook))})
        task = asyncio.create_task(run())
        self.hook_tasks.add(task)
        task.add_done_callback(self.hook_tasks.discard)

    async def close(self) -> None:
        self._worker.cancel()
        for t in list(self.hook_tasks):
            t.cancel()
        await asyncio.gather(self._worker, *self.hook_tasks, return_exceptions=True)
