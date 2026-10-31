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
