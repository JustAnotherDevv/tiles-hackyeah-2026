import localUnitTest from './LocalUnit.test';
import redactorTest from './Redactor.test';
import eligibilityTest from './Eligibility.test';

export default function testsuite() {
  localUnitTest();
  redactorTest();
  eligibilityTest();
}
