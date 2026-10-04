import { describe, it, expect } from '@ohos/hypium';
import { AuthCode, StepUpCodes, StepUpOutcome } from '../main/ets/platform/StepUpCodes';

// Fail-closed rules for the User Authentication Kit step-up (UserAuthResultCode 12500000-12500013).
// Only the pre-check may return 'unavailable' (which opens the labelled manual fallback); every post-start code
// other than SUCCESS must be 'failed' or 'cancelled'.
export default function stepUpAuthTest() {
  describe('StepUpAuthOutcome', () => {
    it('successIsVerifiedWithMethod', 0, () => {
      const o: StepUpOutcome = StepUpCodes.outcomeOf(12500000, 'face');
      expect(o.status).assertEqual('verified');
      expect(o.detail).assertEqual('face');
      expect(StepUpCodes.outcomeOf(AuthCode.SUCCESS, '').status).assertEqual('verified');
    });

    it('everyNonSuccessCodeFailsClosed', 0, () => {
      for (let c = 12500001; c <= 12500013; c++) {
        const o: StepUpOutcome = StepUpCodes.outcomeOf(c, 'face');
        expect(o.status === 'verified').assertFalse();
        expect(o.status === 'unavailable').assertFalse();
        expect(o.detail.length > 0).assertTrue();
      }
    });

    it('fullCodeTable', 0, () => {
      const expected: string[] = [
        'verified', // 12500000 SUCCESS
        'failed', // 12500001 FAIL
        'failed', // 12500002 GENERAL_ERROR (transient: must not open the fallback)
        'cancelled', // 12500003 CANCELED
        'failed', // 12500004 TIMEOUT
        'failed', // 12500005 TYPE_NOT_SUPPORT
        'failed', // 12500006 TRUST_LEVEL_NOT_SUPPORT
        'failed', // 12500007 BUSY
        'failed', // 12500008 INVALID_PARAMETERS
        'failed', // 12500009 LOCKED
        'failed', // 12500010 NOT_ENROLLED (mid-flow)
        'cancelled', // 12500011 CANCELED_FROM_WIDGET
        'failed', // 12500012 (not defined by the Kit)
        'failed' // 12500013 PIN_EXPIRED
      ];
      for (let i = 0; i < expected.length; i++) {
        expect(StepUpCodes.outcomeOf(12500000 + i, 'PIN').status).assertEqual(expected[i]);
      }
    });

    it('specificMessages', 0, () => {
      expect(StepUpCodes.outcomeOf(AuthCode.FAIL, '').detail).assertContain('Not recognised');
      expect(StepUpCodes.outcomeOf(AuthCode.BUSY, '').detail).assertContain('busy');
      expect(StepUpCodes.outcomeOf(AuthCode.LOCKED, '').detail).assertContain('locked');
      expect(StepUpCodes.outcomeOf(AuthCode.PIN_EXPIRED, '').detail).assertContain('PIN has expired');
      expect(StepUpCodes.outcomeOf(201, '').status).assertEqual('failed');
    });
  });

  describe('StepUpAuthPrecheck', () => {
    it('usableAuthenticatorProceeds', 0, () => {
      expect(StepUpCodes.precheckOutcome(1, [AuthCode.NOT_ENROLLED, AuthCode.TYPE_NOT_SUPPORT]) === undefined)
        .assertTrue();
    });

    it('noAuthenticatorIsUnavailable', 0, () => {
      const o: StepUpOutcome | undefined = StepUpCodes.precheckOutcome(0,
        [AuthCode.TYPE_NOT_SUPPORT, AuthCode.NOT_ENROLLED, AuthCode.TRUST_LEVEL_NOT_SUPPORT]);
      expect(o !== undefined && o.status === 'unavailable').assertTrue();
    });

    it('expiredPinOrErrorFailsClosed', 0, () => {
      const pin: StepUpOutcome | undefined = StepUpCodes.precheckOutcome(0,
        [AuthCode.TYPE_NOT_SUPPORT, AuthCode.TYPE_NOT_SUPPORT, AuthCode.PIN_EXPIRED]);
      expect(pin !== undefined && pin.status === 'failed').assertTrue();
      const gen: StepUpOutcome | undefined = StepUpCodes.precheckOutcome(0,
        [AuthCode.TYPE_NOT_SUPPORT, AuthCode.GENERAL_ERROR, AuthCode.NOT_ENROLLED]);
      expect(gen !== undefined && gen.status === 'failed').assertTrue();
    });
  });
}
