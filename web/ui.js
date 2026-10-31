// Small DOM helpers shared by the call pages.

export function transcriptView(el) {
  const partials = {}; // channel -> element showing the in-progress turn
  return {
    show(ev) {
      const ch = ev.channel;
      let node = partials[ch];
      if (!node) {
        node = document.createElement('div');
        node.innerHTML = '<span class="lat"></span><div class="who"></div><div class="text"></div>';
        node.querySelector('.who').textContent = ch;
        el.appendChild(node);
        partials[ch] = node;
      }
      node.className = `turn ${ch}${ev.final ? '' : ' partial'}`;
      node.querySelector('.text').textContent = ev.text; // each Turn supersedes the last
      if (ev.final) {
        if (ev.stt_latency_ms != null) node.querySelector('.lat').textContent = `STT ${ev.stt_latency_ms} ms`;
        delete partials[ch];
      }
      el.scrollTop = el.scrollHeight;
    },
  };
}

export function statusView(el) {
  const state = { parties: [], stt: {} };
  const render = () => {
    const stt = Object.entries(state.stt)
      .map(([ch, s]) => `${ch} STT: <span class="${s.ok ? 'ok' : 'bad'}">${s.ok ? s.model : s.error}</span>`)
      .join(' · ');
    el.innerHTML = `On the line: ${state.parties.join(', ') || 'nobody'}${stt ? ' · ' + stt : ''}`;
  };
  return {
    handle(ev) {
      if (ev.type === 'presence') state.parties = ev.parties;
      else if (ev.type === 'stt_status') state.stt[ev.channel] = ev;
      else return false;
      render();
      return true;
    },
  };
}

export function levelMeter(el) {
  return (int16) => {
    let peak = 0;
    for (let i = 0; i < int16.length; i++) peak = Math.max(peak, Math.abs(int16[i]));
    el.style.width = `${Math.min(100, (peak / 0x7fff) * 140)}%`;
  };
}

const STAGE_LABELS = {
  S1: 'Authority', S2: 'Threat', S3: 'Secrecy', S4: 'Urgency', S5: 'Credentials', S6: 'Payment', S7: 'Remote access',
};

// Stage chips + cumulative risk meter + latest rationale. Call handle(ev) with each server event.
export function detectionView(el) {
  el.innerHTML = `
    <div class="row" style="justify-content:space-between">
      <strong>Scam risk <span id="riskNum">0</span></strong>
      <span id="riskState" class="muted">listening</span>
    </div>
    <div class="riskbar"><div id="riskFill"></div></div>
    <div class="chips" id="chips"></div>
    <p class="muted" id="rationale"></p>`;
  const chips = el.querySelector('#chips');
  chips.innerHTML = Object.entries(STAGE_LABELS)
    .map(([k, v]) => `<span class="chip" data-s="${k}" title="${k}">${v}</span>`).join('');
  const q = (id) => el.querySelector(id);
  return {
    handle(ev) {
      if (ev.type !== 'detection') return false;
      if (ev.error) { q('#riskState').textContent = 'detector unavailable'; return true; }
      q('#riskNum').textContent = Math.round(ev.risk_cum);
      const fill = q('#riskFill');
      fill.style.width = `${ev.risk_cum}%`;
      fill.className = ev.risk_cum >= 70 ? 'high' : ev.risk_cum >= 40 ? 'mid' : '';
      q('#riskState').textContent = ev.trigger ? `WARNING (${ev.reason}) · ${ev.llm_ms} ms` : `${ev.llm_ms} ms`;
      q('#riskState').style.color = ev.trigger ? 'var(--danger)' : '';
      for (const c of chips.children) {
        c.classList.toggle('on', ev.stages_all.includes(c.dataset.s));
        c.classList.toggle('now', ev.stages_now.includes(c.dataset.s));
      }
      q('#rationale').textContent = ev.rationale || '';
      return true;
    },
  };
}
