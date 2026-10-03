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
  });
}
