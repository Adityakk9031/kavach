"""What happens when a call ends: write the complaint draft and tell the family, but only for calls that were flagged."""

import asyncio

from app import report as report_mod


def was_flagged(room) -> bool:
    """A call is worth a complaint draft only if Kavach actually flagged it (warning triggered or takeover used).
    Merely mentioning a phone number or a website (a delivery agent, say) must not produce a complaint."""
    pipeline_triggered = room.pipeline is not None and room.pipeline.triggered
    took_over = room.takeover or (room.persona is not None and (room.persona.active or room.persona.replies > 0))
    return bool(pipeline_triggered or took_over)


def make_finalize(room, store, settings):
    async def finalize() -> dict:
        # Let the last detections and evidence land first.
        for q in (room.pipeline.queue, room.evidence.queue):
            try:
                await asyncio.wait_for(q.join(), 8)
            except asyncio.TimeoutError:
                room.log_event("finalize_timeout", {})
        if not was_flagged(room):
            return {}
        r, md, pdf = report_mod.generate(store, room.call_id, settings.reports_dir)
        n = sum(len(v) for v in r.evidence.values())
        await room.alerts.call_ended(
            f"📄 Kavach: call ended. Complaint draft ready with {n} captured detail(s). Review it, then file at "
            f"cybercrime.gov.in or call 1930. (Draft only: nothing was submitted.)", pdf)
        await room.alerts.drain()
        room.log_event("report_ready", {"md": str(md), "pdf": str(pdf), "details": n})
        return {"report": {"md": f"/api/calls/{room.call_id}/report.md", "pdf": f"/api/calls/{room.call_id}/report.pdf"}}

    return finalize
