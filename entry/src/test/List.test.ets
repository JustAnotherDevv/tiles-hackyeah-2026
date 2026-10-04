import localUnitTest from './LocalUnit.test';
import redactorTest from './Redactor.test';

export default function testsuite() {
  localUnitTest();
  redactorTest();
}
