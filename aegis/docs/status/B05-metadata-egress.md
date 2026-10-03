# B05-metadata-egress — status

Owner paths: `src/aegis/egress/**`, `src/aegis/controls/egress/**`, `src/aegis/api/routes/egress.py`,
`config/snippets/metadata-egress.yaml`, `tests/unit/metadata_egress/**`.

## Tasks
| ID | State | Notes |
|---|---|---|
| META-01 | done | params (profile defaults, legacy seed keys), policyview, compat fallbacks, snippet (3 controls, 18 inline tests) |
| META-02 | done | `textmeta.py`: path users, internal hosts, private IPs, MAC, git identities, learned identifiers; bisect overlap resolution |
| META-03 | done | DLP-03 `MetadataStrip`: matrix gate, header plan, `metadata.user_id` pseudonyms, text findings, meta summary, metrics |
| META-04 | done | `encoded.py`, `exfil.py`, DLP-04 `EgressExfilScan` (URL/DNS/OAST/userinfo/IP/IDN/shell/query blobs + arg blobs) |
| META-05 | done | `channels.py`, DLP-06 (md inline/reference images, HTML tags, suspicious links, OSC/OSC-8); also covers `egress.response` (A-42 could) |
| META-06 | done | `hostmap.py`, `forwarder.py`, `POST /egress` (validation 400, block 403 / stop 402/429 via `core.errors.verdict_error`, approval 403 + `X-Aegis-Approval-Id`, 502 unmapped `.test`/connect errors, response hop on same ctx, `attach_response`, `complete()` exactly once, `X-Aegis-*` + `Server-Timing`, startup `system` event) |
| META-07 | done | `claude_code.py` recognizers + `replay` CLI; fixtures in `aegis.egress.fixtures` (no JSON files on disk) |
| META-08 | done | `media/{jpeg,png}.py`, `blobs.py`, `metadata.py` (`sniff`, `sanitize_bytes`, `scan_raw_media`); DLP-03 body `set` mutation keeps data-URI prefix; HEIC/AVIF/TIFF → unsupported → block (balanced) |
| META-09 | done | `python -m aegis.egress.fixtures <dir>`, `python -m aegis.egress.metadata inspect|strip`, `python -m aegis.egress.claude_code replay` |
| META-10 | done | `media/pdf.py` (same-length Info/XMP blanking, /Encrypt + ObjStm → unsupported, active content reported), `media/office.py` (docProps, comments, people, thumbnail, `w:author`; tracked changes reported) |
| META-11 | done | profile defaults permissive/balanced/strict/paranoid; tests in `test_dlp03.py::test_profiles`, `test_claude_code.py` strict/paranoid |
| META-12 | done | text + media LRU caches, learned-identifier cache, `model_construct` findings, `to_thread` > 256 KB |
| META-13 | done | `aegis_metadata_stripped_total{kind}`, `aegis_egress_requests_total{result,dest_class}`, `aegis_exfil_hits_total{channel}` (guarded), startup system event |
| META-14 | not started (could) | WebP/GIF with metadata → reported `unsupported`; no pypdf |
| META-15 | done (could) | DLP-04 semantic leg behind `params.semantic_judge` (masked summary) |
| META-16 | not started (could) | credential injection / external-host denylist |

## Verification
- V01 import/plugin shape: `['DLP-03','DLP-04','DLP-06'] ['deterministic','hybrid','deterministic'] /egress` ✅; `ruff check` owned paths ✅
- V02–V09, V13: `AEGIS_TEST_MODE=1 AEGIS_SEMANTIC=off uv run --frozen pytest tests/unit/metadata_egress -q` → **127 passed** ✅
  (test_textmeta, test_dlp03, test_claude_code, test_encoded, test_exfil [= DLP-04 decisions; no separate test_dlp04.py], test_channels, test_media_jpeg_png, test_blobs, test_media_pdf_office, test_forwarder [fake pipeline + real controls], test_route_egress [real `create_app` stack, MockTransport upstream, marked slow], test_perf)
- V07 manual: `sips` shows Make/Model before, nothing after strip; stripped JPEG decodes. (`sips -g orientation` prints `<nil>` for both the fixture and the output, so orientation=6 retention is proven only by the unit test)
- V08 manual: `mdls kMDItemAuthors` null after strip; PDF length unchanged, xref valid (unit test)
- V10: snippet validates (`['DLP-03','DLP-04','DLP-06'] 18`); `python -m aegis selftest` on live `config/policy.yaml`: 82 passed, incl. DLP-03/04/06 cases ✅
- V11/V12: not run (need `make up` / live Claude Code). In-process real-stack probe: b64 PAN to exfil.test → 403 DLP-01 (deterministic first; DLP-04 hybrid skipped), base32 PESEL DNS label → 403 DLP-04, CRM POST with PESEL → 403 approval_required ACT-03 (waits hold_s 15)
- V13 perf: best-of-20 ~12 ms on 120 KB CC request under load avg 40 (plan target 10 ms idle); test asserts best < 25 ms

## How to demo
- `python -m aegis.egress.fixtures /tmp/fx && python -m aegis.egress.metadata inspect /tmp/fx/photo_gps.jpg` → strip → inspect again
- `curl -XPOST :8787/egress -H 'X-Aegis-Agent: chaos-agent@platform' -H 'content-type: application/json' -d '{"method":"GET","url":"https://kbcvgrkmea2dimbvge2damjtgu4q.exfil.test/"}'` → 403 DLP-04
- `python -m aegis.egress.claude_code replay` (needs gateway + mock_llm)

## deps_needed
none (stdlib only; `pypdf` not used per A-58 decline)

## contract_deviations
- `/egress` 200 body has additive `applied: [...]` (names of applied segment/header/body changes; no values).
- DLP-06 keeps SGR colour escapes (`\x1b[31m`); removes OSC/OSC-8 and non-SGR CSI.
- WebP/GIF *with* EXIF/XMP are `unsupported` (block in balanced) instead of being stripped (META-14 not done).

## integration_todos
- policy-engine: `config/policy.yaml` DLP-03 still uses legacy `params: {strip_body_fields: ...}` (mapped by `egress/params.py::_legacy`); the 18 snippet tests in `config/snippets/metadata-egress.yaml` are not merged into policy.yaml yet.
- core-gateway (A-13/G1): DLP-03 header mutations only take effect on the model path if adapters forward `Interaction.headers` minus `target="header"` mutations and apply `target="body"` mutations (`metadata.user_id`, image blobs).
- audit-metrics: real-stack probe logged "audit scrubber replaced sensitive values" for egress decisions — the recorded `interaction.url` contains query values; consider storing `aegis.egress.exfil.mask_url(url)` for `egress.*` surfaces.
- `/egress` binary downloads are returned as `body_b64` without an `artifact.file` hop (A-13 [should]).
