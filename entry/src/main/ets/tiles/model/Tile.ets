/**
 * Tiles generative-UI data model (docs/TILES_SPEC.md). The assistant (Composer) emits TileSpec JSON with this
 * exact shape; TileView renders it natively. Additive changes only.
 */

export class TileAction {
  label: string = '';
  kind: string = 'done'; // call|remind|speak|open|done|vote|navigate|sos|dismiss
  arg: string = '';
}

export class TileBlock {
  kind: string = 'text'; // text|big|list|checklist|progress|buttons|timer|chips|alert|weather
  text: string = '';
  value: string = '';
  items: string[] = [];
  checked: boolean[] = [];
  progress: number = 0;
  actions: TileAction[] = [];
}

export class TileSpec {
  id: string = '';
  type: string = 'custom'; // pills|call|weather|guardian|plan|timer|homework|screentime|reminder|note|sos|commute|adventure|custom
  title: string = '';
  subtitle: string = '';
  icon: string = ''; // SymbolGlyph name (sys.symbol.<icon>) or resource name
  color: string = 'sky'; // palette key, see TilesTheme
  size: string = '2x1'; // 1x1 | 2x1 | 2x2
  blocks: TileBlock[] = [];
  source: string = 'seed'; // seed|assistant|adaptation
  speakText: string = '';
  pinned: boolean = false;
  createdAt: number = 0;
}

export class Profile {
  id: string = 'everyday'; // senior|kid|lowvision|everyday
  name: string = '';
  textScale: number = 1.0;
  highContrast: boolean = false;
  readAloud: boolean = false;
  columns: number = 4;
  caregiver: string = '';
  caregiverRole: string = '';
}

export class Suggestion {
  id: string = '';
  title: string = '';
  detail: string = '';
  change: string = ''; // e.g. textScale:1.4 | hide:apps | readAloud:on | addTile:<json>
  status: string = 'pending';
  reason: string = '';
}

export class ComposeResult {
  reply: string = '';
  tiles: TileSpec[] = [];
  needsApproval: boolean = false;
  followUps: string[] = [];
}
