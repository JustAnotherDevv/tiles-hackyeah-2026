/**
 * Design tokens for Aegis Pocket. Dark-first palette; every screen reads colors,
 * radii and spacing from here so the UI stays consistent.
 */
export class Colors {
  static readonly BG: string = '#0B0F17';
  static readonly SURFACE: string = '#131A26';
  static readonly SURFACE_2: string = '#1A2333';
  static readonly SURFACE_3: string = '#222D41';
  static readonly BORDER: string = '#243047';
  static readonly TEXT: string = '#E6EDF7';
  static readonly TEXT_DIM: string = '#8A97AD';
  static readonly TEXT_FAINT: string = '#5B6880';
  static readonly ACCENT: string = '#4F8CFF';
  static readonly ACCENT_SOFT: string = '#1C2B4A';
  static readonly GOOD: string = '#2FD08A';
  static readonly GOOD_SOFT: string = '#123326';
  static readonly WARN: string = '#F5B544';
  static readonly WARN_SOFT: string = '#3A2C12';
  static readonly BAD: string = '#FF5A6A';
  static readonly BAD_SOFT: string = '#3D1A20';
  static readonly VIOLET: string = '#A78BFA';
  static readonly VIOLET_SOFT: string = '#2A2247';
  static readonly SKY: string = '#38BDF8';
  static readonly SKY_SOFT: string = '#11304A';
  static readonly FUCHSIA: string = '#E879F9';
  static readonly FUCHSIA_SOFT: string = '#3A1A40';
  static readonly TEAL: string = '#2DD4BF';
  static readonly TEAL_SOFT: string = '#0F3533';
  static readonly SLATE: string = '#94A3B8';
  static readonly SLATE_SOFT: string = '#1E2633';
}

export class Space {
  static readonly XS: number = 4;
  static readonly SM: number = 8;
  static readonly MD: number = 12;
  static readonly LG: number = 16;
  static readonly XL: number = 24;
  static readonly PAGE: number = 16;
}

export class Radius {
  static readonly SM: number = 8;
  static readonly MD: number = 14;
  static readonly LG: number = 20;
  static readonly PILL: number = 999;
}

export class Fonts {
  static readonly TITLE: number = 26;
  static readonly H2: number = 18;
  static readonly BODY: number = 15;
  static readonly SMALL: number = 13;
  static readonly TINY: number = 11;
  static readonly KPI: number = 28;
}

/** Colors for a role / approver level, following the Aegis dashboard (owner fuchsia, admin sky, member slate). */
export class RoleTone {
  fg: string;
  bg: string;

  constructor(fg: string, bg: string) {
    this.fg = fg;
    this.bg = bg;
  }

  static of(level: string): RoleTone {
    if (level === 'owner') {
      return new RoleTone(Colors.FUCHSIA, Colors.FUCHSIA_SOFT);
    }
    if (level === 'admin') {
      return new RoleTone(Colors.SKY, Colors.SKY_SOFT);
    }
    if (level === 'auto') {
      return new RoleTone(Colors.GOOD, Colors.GOOD_SOFT);
    }
    if (level === 'deny') {
      return new RoleTone(Colors.BAD, Colors.BAD_SOFT);
    }
    return new RoleTone(Colors.SLATE, Colors.SLATE_SOFT);
  }

  static ofStatus(status: string): RoleTone {
    if (status === 'approved') {
      return new RoleTone(Colors.GOOD, Colors.GOOD_SOFT);
    }
    if (status === 'denied') {
      return new RoleTone(Colors.BAD, Colors.BAD_SOFT);
    }
    if (status === 'pending') {
      return new RoleTone(Colors.VIOLET, Colors.VIOLET_SOFT);
    }
    return new RoleTone(Colors.SLATE, Colors.SLATE_SOFT);
  }
}
