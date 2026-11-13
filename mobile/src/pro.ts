// Full protection: what the call service on this phone says about Shizuku, and the few things the app can ask it to do.
// The two talk through small files in the app's own folder (the service writes kavach-status.json, the app writes
// kavach-cmd.json), the same way the account reaches the service.
import * as FileSystem from 'expo-file-system/legacy';

export type ProStatus = {
  alive: boolean; installed: boolean; running: boolean; allowed: boolean; secure: boolean; wireless: boolean; cmdId: string; cmdResult: string;
};
export type ProCmd = 'pro_setup' | 'pro_wake' | 'open_shizuku';
export const NONE: ProStatus = { alive: false, installed: false, running: false, allowed: false, secure: false, wireless: false, cmdId: '', cmdResult: '' };

const dir = () => FileSystem.documentDirectory ?? '';

// "alive" means the call service wrote its status in the last 15 seconds, so call protection is switched on
export async function readPro(): Promise<ProStatus> {
  try {
    const o = JSON.parse(await FileSystem.readAsStringAsync(dir() + 'kavach-status.json'));
    return { alive: Date.now() - Number(o.t ?? 0) < 15000, installed: !!o.installed, running: !!o.running, allowed: !!o.allowed,
      secure: !!o.secure, wireless: !!o.wireless, cmdId: String(o.cmd_id ?? ''), cmdResult: String(o.cmd_result ?? '') };
  } catch { return NONE; }
}

export async function sendPro(cmd: ProCmd): Promise<string> {
  const id = `${Date.now()}`;
  try { await FileSystem.writeAsStringAsync(dir() + 'kavach-cmd.json', JSON.stringify({ id, cmd })); } catch { /* the screen shows no answer */ }
  return id;
}

// What the service answered, as the name of one of the app's own texts (or '' while there is nothing to say)
export function proMessage(result: string): string {
  switch (result) {
    case 'shizuku_off': return 'pro_r_shizuku';
    case 'need_allow': return 'pro_r_allow';
    case 'grant_failed': case 'no_secure': case 'error': return 'pro_r_fail';
    case 'wireless': return 'pro_wakeDone';
    case 'ok': return 'pro_done';
    default: return '';
  }
}
