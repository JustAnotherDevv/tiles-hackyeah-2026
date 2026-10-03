// Typed mock factories for the Security pages (fallback on 404/405/501/network, or forced with ?mock=1).
// ?scenario=tamper (feed rejected) · broken (audit broken at seq 1234) · rugpull (changed MCP tool) · disabled (DLP-02 off).
// Owner: dashboard-security.
export { MOCK_AGENTS, agentIdentity, memberIdentity, mockAgents } from './cast';
export { mockControls, mockHealth } from './controls';
export { mockCoverage } from './coverage';
export {
  DEMO_IDS,
  MOCK_FEED_SERIAL,
  MOCK_POLICY_VERSION,
  makeMockDecision,
  mockDecisionDetail,
  mockDecisionPage,
  mockSignatureHits,
  toSummary,
} from './decisions';
export { mockFeedSignatures, mockFeedStatus } from './feed';
export { mockMcpServers } from './mcp';
export { mockAuditPage, mockAuditVerify } from './audit';
export { mockBench, mockPerf } from './perf';
export { mockPlayground } from './playground';
export { startMockDecisionStream } from './stream';
export { fakeAwsKeyId, fakeAwsSecret } from './rng';
