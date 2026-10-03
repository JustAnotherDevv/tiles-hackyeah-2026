import { Colors, Fonts, Radius, Space } from '../common/Theme';
import { Finding, RedactionResult, Redactor, SAMPLE_TEXT } from '../redaction/Redactor';
import { ScreenHeader } from '../components/Common';

class Segment {
  key: string;
  text: string;
  redacted: boolean;

  constructor(key: string, text: string, redacted: boolean) {
    this.key = key;
    this.text = text;
    this.redacted = redacted;
  }
}

class EntityCount {
  entity: string;
  count: number;

  constructor(entity: string, count: number) {
    this.entity = entity;
    this.count = count;
  }
}

/**
 * "What data leaves" preview. The user types or pastes text; personal data is detected and
 * replaced by placeholders entirely on this device (no network call, nothing stored). This is
 * the same local-first redaction the Aegis gateway applies before a prompt reaches a remote model.
 */
@Component
export struct PreviewView {
  @State input: string = '';
  @State segments: Segment[] = [];
  @State findings: Finding[] = [];
  @State entityCounts: EntityCount[] = [];

  build() {
    Scroll() {
      Column({ space: Space.LG }) {
        ScreenHeader({ title: 'What data leaves', subtitle: 'On-device preview · nothing is sent' })

        Column({ space: Space.LG }) {
          Row({ space: Space.SM }) {
            Text('LOCAL')
              .fontSize(9)
              .fontWeight(FontWeight.Bold)
              .fontColor(Colors.GOOD)
              .padding({ left: 6, right: 6, top: 2, bottom: 2 })
              .borderRadius(4)
              .backgroundColor(Colors.GOOD_SOFT)
            Text('Detection runs in ArkTS on this phone. Emails, phone numbers, PESEL, IBAN and card numbers ' +
              '(checksum-validated) are replaced before anything would reach an AI model.')
              .fontSize(Fonts.SMALL)
              .fontColor(Colors.TEXT_DIM)
              .layoutWeight(1)
          }
          .alignItems(VerticalAlign.Top)
          .width('100%')

          TextArea({ placeholder: 'Type or paste a prompt, an email, a support ticket…', text: $$this.input })
            .fontSize(Fonts.BODY)
            .fontColor(Colors.TEXT)
            .placeholderColor(Colors.TEXT_FAINT)
            .backgroundColor(Colors.SURFACE)
            .borderRadius(Radius.MD)
            .border({ width: 1, color: Colors.BORDER })
            .height(150)
            .onChange((v: string) => {
              this.input = v;
              this.analyse();
            })

          Row({ space: Space.SM }) {
            Button('Load sample')
              .fontSize(Fonts.SMALL)
              .fontColor(Colors.TEXT)
              .backgroundColor(Colors.SURFACE_2)
              .height(36)
              .onClick(() => {
                this.input = SAMPLE_TEXT;
                this.analyse();
              })
            Button('Clear')
              .fontSize(Fonts.SMALL)
              .fontColor(Colors.TEXT_DIM)
              .backgroundColor(Colors.SURFACE_2)
              .height(36)
              .onClick(() => {
                this.input = '';
                this.analyse();
              })
            Blank()
            Text(this.findings.length.toString() + ' found')
              .fontSize(Fonts.SMALL)
              .fontColor(this.findings.length > 0 ? Colors.WARN : Colors.TEXT_DIM)
          }
          .width('100%')

          if (this.input.length > 0) {
            Column({ space: Space.SM }) {
              Row() {
                Text('WHAT WOULD LEAVE THE DEVICE')
                  .fontSize(Fonts.TINY)
                  .fontColor(Colors.TEXT_DIM)
                  .letterSpacing(1)
                Blank()
              }
              .width('100%')

              Text() {
                ForEach(this.segments, (s: Segment) => {
                  Span(s.text)
                    .fontColor(s.redacted ? Colors.WARN : Colors.TEXT)
                    .fontWeight(s.redacted ? FontWeight.Bold : FontWeight.Normal)
                    .textBackgroundStyle({ color: s.redacted ? Colors.WARN_SOFT : Color.Transparent, radius: 4 })
                }, (s: Segment) => s.key + ':' + s.text)
              }
              .fontSize(Fonts.BODY)
              .lineHeight(24)
              .width('100%')
            }
            .padding(Space.LG)
            .width('100%')
            .borderRadius(Radius.LG)
            .backgroundColor(Colors.SURFACE)
            .border({ width: 1, color: Colors.BORDER })
            .transition(TransitionEffect.OPACITY.animation({ duration: 250 }))
          }

          if (this.entityCounts.length > 0) {
            Row({ space: 6 }) {
              ForEach(this.entityCounts, (e: EntityCount) => {
                Text(e.entity + ' ×' + e.count.toString())
                  .fontSize(Fonts.TINY)
                  .fontWeight(FontWeight.Bold)
                  .fontColor(Colors.WARN)
                  .padding({ left: 8, right: 8, top: 3, bottom: 3 })
                  .borderRadius(Radius.PILL)
                  .backgroundColor(Colors.WARN_SOFT)
              }, (e: EntityCount) => e.entity)
            }
            .width('100%')
          }

          if (this.findings.length > 0) {
            Column() {
              Text('STAYS ON THIS DEVICE')
                .fontSize(Fonts.TINY)
                .fontColor(Colors.TEXT_DIM)
                .letterSpacing(1)
                .width('100%')
                .margin({ bottom: Space.SM })
              ForEach(this.findings, (f: Finding, idx: number) => {
                Row({ space: Space.SM }) {
                  Text(f.placeholder)
                    .fontSize(Fonts.SMALL)
                    .fontFamily('monospace')
                    .fontColor(Colors.WARN)
                    .width(110)
                  Text(f.masked)
                    .fontSize(Fonts.SMALL)
                    .fontFamily('monospace')
                    .fontColor(Colors.TEXT_DIM)
                    .layoutWeight(1)
                    .maxLines(1)
                    .textOverflow({ overflow: TextOverflow.Ellipsis })
                }
                .width('100%')
                .padding({ top: 6, bottom: 6 })
                .border({ width: { top: idx === 0 ? 0 : 1 }, color: Colors.BORDER })
              }, (f: Finding) => f.placeholder + '@' + f.start.toString())
              Text('Original values are masked here too. The gateway keeps the mapping locally and can ' +
                'restore placeholders in the model\'s answer.')
                .fontSize(Fonts.TINY)
                .fontColor(Colors.TEXT_FAINT)
                .margin({ top: Space.SM })
            }
            .padding(Space.LG)
            .width('100%')
            .borderRadius(Radius.LG)
            .backgroundColor(Colors.SURFACE)
            .border({ width: 1, color: Colors.BORDER })
          }
        }
        .padding({ left: Space.PAGE, right: Space.PAGE, bottom: Space.XL })
      }
    }
    .scrollBar(BarState.Off)
    .edgeEffect(EdgeEffect.Spring)
    .align(Alignment.Top)
    .width('100%')
    .height('100%')
  }

  private analyse(): void {
    const res: RedactionResult = Redactor.redact(this.input);
    const segs: Segment[] = [];
    let cursor: number = 0;
    let n: number = 0;
    for (const f of res.findings) {
      if (f.start > cursor) {
        segs.push(new Segment('t' + n.toString(), this.input.substring(cursor, f.start), false));
        n++;
      }
      segs.push(new Segment('p' + n.toString(), f.placeholder, true));
      n++;
      cursor = f.start + f.length;
    }
    if (cursor < this.input.length) {
      segs.push(new Segment('t' + n.toString(), this.input.substring(cursor), false));
    }
    this.segments = segs;
    this.findings = res.findings;
    const counts: EntityCount[] = [];
    res.counts.forEach((v: number, k: string) => {
      counts.push(new EntityCount(k, v));
    });
    this.entityCounts = counts;
  }
}
