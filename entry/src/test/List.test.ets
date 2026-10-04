import localUnitTest from './LocalUnit.test';
import redactorTest from './Redactor.test';
import eligibilityTest from './Eligibility.test';
import stepUpRiskTest from './StepUpRisk.test';

export default function testsuite() {
  localUnitTest();
  redactorTest();
  eligibilityTest();
  stepUpRiskTest();
}
