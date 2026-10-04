import { describe, it, expect } from '@ohos/hypium';
import { Checksums, RedactionResult, Redactor, SAMPLE_TEXT } from '../main/ets/redaction/Redactor';

// Local unit tests for the on-device "What data leaves" redactor (host-side, no device needed).
export default function redactorTest() {
  describe('Redactor', () => {
    it('validatesChecksums', 0, () => {
      expect(Checksums.pesel('44051401359')).assertTrue();
      expect(Checksums.pesel('44051401358')).assertFalse();
      expect(Checksums.luhn('4111 1111 1111 1111')).assertTrue();
      expect(Checksums.luhn('4111 1111 1111 1112')).assertFalse();
      expect(Checksums.iban('PL61 1090 1014 0000 0712 1981 2874')).assertTrue();
      expect(Checksums.iban('PL61 1090 1014 0000 0712 1981 2875')).assertFalse();
    });

    it('redactsSampleWithStablePlaceholders', 0, () => {
      const r: RedactionResult = Redactor.redact(SAMPLE_TEXT);
      expect(r.text).assertContain('[EMAIL_1]');
      expect(r.text).assertContain('[EMAIL_2]');
      expect(r.text).assertContain('[PESEL_1]');
      expect(r.text).assertContain('[IBAN_1]');
      expect(r.text).assertContain('[PAN_1]');
      expect(r.text).assertContain('[PHONE_1]');
      expect(r.text.indexOf('44051401359')).assertEqual(-1);
      expect(r.text.indexOf('4111')).assertEqual(-1);
    });

    it('reusesPlaceholderForSameValue', 0, () => {
      const r: RedactionResult = Redactor.redact('a@example.com then A@Example.com');
      expect(r.text).assertEqual('[EMAIL_1] then [EMAIL_1]');
    });

    it('leavesInvalidNumbersAlone', 0, () => {
      const r: RedactionResult = Redactor.redact('id 12345678901 card 4111 1111 1111 1112');
      expect(r.findings.length).assertEqual(0);
    });

    it('masksCardsPciStyle', 0, () => {
      expect(Redactor.mask('PAN', '4111 1111 1111 1111')).assertEqual('411111******1111');
    });

    it('handlesEmptyInput', 0, () => {
      const r: RedactionResult = Redactor.redact('');
      expect(r.text).assertEqual('');
      expect(r.findings.length).assertEqual(0);
      expect(r.counts.size).assertEqual(0);
    });

    it('handlesHugeInputQuickly', 0, () => {
      const big: string = 'x'.repeat(200000) + 'a@b.co';
      const t0: number = Date.now();
      const r: RedactionResult = Redactor.redact(big);
      const elapsed: number = Date.now() - t0;
      expect(elapsed < 500).assertTrue();
      expect(r.findings.length).assertEqual(1);
      expect(r.findings[0].entity).assertEqual('EMAIL');
    });

    it('handlesLongDigitRunsQuickly', 0, () => {
      // Formerly the PHONE pattern was attempted at every digit of a long run.
      const t0: number = Date.now();
      const r: RedactionResult = Redactor.redact('1'.repeat(100000) + ' ' + '1 '.repeat(50000));
      expect(Date.now() - t0 < 500).assertTrue();
      expect(r.findings.length).assertEqual(0);
    });

    it('keepsAdjacentFindingsSeparate', 0, () => {
      const input: string = 'a@b.co4111111111111111';
      const r: RedactionResult = Redactor.redact(input);
      expect(r.findings.length).assertEqual(2);
      expect(r.findings[0].entity).assertEqual('EMAIL');
      expect(r.findings[1].entity).assertEqual('PAN');
      expect(r.findings[0].start + r.findings[0].length <= r.findings[1].start).assertTrue();
      expect(r.text).assertEqual('[EMAIL_1][PAN_1]');
    });

    it('neverDoubleCountsOverlappingCandidates', 0, () => {
      // The card digits also look like a phone; the digits before '@' also look like a phone.
      const r: RedactionResult = Redactor.redact('card 4111 1111 1111 1111, mail 601234567@example.com');
      expect(r.findings.length).assertEqual(2);
      expect(r.findings[0].entity).assertEqual('PAN');
      expect(r.findings[1].entity).assertEqual('EMAIL');
      expect(r.text).assertEqual('card [PAN_1], mail [EMAIL_1]');
    });

    it('preservesUnicodeAndUtf16Offsets', 0, () => {
      const input: string = 'Zażółć a@b.co 😀 +48 601 234 567';
      const r: RedactionResult = Redactor.redact(input);
      expect(r.findings.length).assertEqual(2);
      expect(r.text).assertEqual('Zażółć [EMAIL_1] 😀 [PHONE_1]');
      expect(input.substring(r.findings[0].start, r.findings[0].start + r.findings[0].length)).assertEqual('a@b.co');
      expect(input.substring(r.findings[1].start, r.findings[1].start + r.findings[1].length))
        .assertEqual('+48 601 234 567');
    });

    it('detectsLowercaseIbanFollowedByWord', 0, () => {
      const r: RedactionResult = Redactor.redact('pay pl61 1090 1014 0000 0712 1981 2874 from today');
      expect(r.findings.length).assertEqual(1);
      expect(r.findings[0].entity).assertEqual('IBAN');
      expect(r.text).assertEqual('pay [IBAN_1] from today');
    });
  });
}
