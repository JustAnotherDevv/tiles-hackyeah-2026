import localUnitTest from './LocalUnit.test';
import redactorTest from './Redactor.test';
import eligibilityTest from './Eligibility.test';
import stepUpRiskTest from './StepUpRisk.test';
import liveMappingTest from './LiveMapping.test';
import stepUpAuthTest from './StepUpAuth.test';
import notificationPolicyTest from './NotificationPolicy.test';
import pocketPersistTest from './PocketPersist.test';
import pocketStoreTest from './PocketStore.test';

export default function testsuite() {
  localUnitTest();
  redactorTest();
  eligibilityTest();
  stepUpRiskTest();
  liveMappingTest();
  stepUpAuthTest();
  notificationPolicyTest();
  pocketPersistTest();
  pocketStoreTest();
}
