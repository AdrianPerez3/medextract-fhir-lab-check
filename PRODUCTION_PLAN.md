# MedExtract FHIR Lab Check implementation and release plan

This record describes the 0.3.0rc1 baseline, an offline quality-assurance CLI and Python library for implementers exchanging FHIR R4 laboratory results. A team should be able to install the distribution, verify its installation, compare its own synthetic test export, and interpret a failing or unevaluable case in CI. The reference must be independent of the candidate. Existing v1/v2 contracts, public `check` and `bind` behavior, and the 0/1/2 exit convention are compatibility requirements.

## Delivery sequence

| Stage and owner | Implementation | Evidence required to close |
| --- | --- | --- |
| 1 · Maintainer, establish the baseline | Freeze the 0.2.0 archive, record its digest, run the previous test suite, and review the current entry points and published promises. | The 74 original members match the starting tree, the archive digest matches the earlier release record, and the original 123 tests pass. |
| 2 · Fidelity maintainer, close false passes | Reproduce each discrepancy with independently constructed synthetic inputs. Apply the smallest rule justified by the source contract and R4. Include a neighboring valid control, such as extra coding systems or a compatible reference. | Each new regression fails on the applicable old behavior and passes on the candidate. Existing supported examples still give their recorded results. |
| 3 · CLI maintainer, unify single and batch evaluation | Share reference, binding, row and optional narrative evaluation across commands. Keep informative exit codes, distinguish unsupported inputs from detected errors, and retain a finding when another independent check fails. Surface errors without printing input file paths or clinical literals in diagnostics. | Repeat the same mixed case through both CLI paths. Verify both the findings and the eligible row denominator. Test malformed/missing inputs, a clean pass and an intentional mismatch. |
| 4 · Performance maintainer, reduce repeated work | Measure representative small and larger reports before editing. Profile binding and checking separately from parsing. Preserve the independent-copy promise for callers of the public binding API. | Compare the same serialized fixtures and outcomes against the pinned baseline; repeat timings and measure peak memory separately. Record workload, interpreter and scope of results. |
| 5 · Release maintainer, ship an installable tool | Include a working offline demo, schema and applicable notices. Build a source distribution, build a wheel from that archive and install it outside the checkout. Configure a read-only CI workflow covering supported host families. | Check package metadata, installed files, demo, explicit CLI calls, expected exits and tests. Distinguish local platform runs from configured hosted jobs. |
| 6 · Independent reviewer, qualify the candidate | Recheck docs, exact shipped files, rights and notices, local-path and secret-pattern scan, archive digests, synthetic corpus replay and unit suite. Keep artifacts immutable and store results next to the release candidate. | Unpack the final artifact, verify digests, rerun checks and compare the 1,000-report replay with its original receipt. Record every outstanding release gate. |
| 7 · Receiving team and maintainer, promote a stable release | Run hosted CI for the reviewed revision. Have a receiving integration team run its own converter with independently reviewed source rows. Resolve confirmed regressions and record expected unsupported representations. Tag and publish the exact approved bytes when authorized. | Hosted checks pass for the intended OS/Python matrix. The team can install offline, identify a deliberately changed result, retain missing reports in its denominator, and reproduce an actionable issue using a synthetic example. |

## Production operating contract

- **Inputs.** One report per candidate bundle, direct results, and independently attested row identifiers or explicit source-to-resource bindings. Keep fixtures in a stable local directory while a suite is running. Archive the fixture version, FHIR/profile version and checker version with results.
- **Automation.** For `check` and `suite`, exit 0 means all requested comparisons passed. The `demo` self-test exits 0 when outcomes match its recorded passes and deliberately failing controls. Exit 1 means an evaluable discrepancy. Exit 2 requires inspection of the unevaluable inputs or the indicated stage. Preserve the full suite output, since an unevaluable case can coexist with an established discrepancy. Use synthetic identifiers when retaining logs.
- **Qualification.** Run the applicable HL7 profile and terminology checks on the original candidate separately. Local file comparison checks fidelity to the supplied reference. A receiving site controls verification of terminology mappings, clinical appropriateness, patient identity resolution, data handling and use with its workflow.
- **Recovery.** Keep the previous wheel/archive, reference version and case receipt. Run old and new versions on the same frozen cases before changing a CI gate. Investigate changes by report and finding code. Restore the previously accepted environment if a release changes eligible results unexpectedly.
- **Follow-on engineering.** Correction/retransmission chronology, panel membership and clinically justified unit conversion require expanded reference contracts and independently reviewed fixtures. [Research priorities](research/next-improvements.md)

## Verification record

### Results from 24 November 2026

| Check | Result |
| --- | --- |
| Starting point | All 123 tests passed against the 74-file 0.2.0 preview. Its ZIP SHA-256 is `6c35af5791ba54b7b6d14221b081f087ea6ea4eeb9adc694227f28ce3d5ed00f`. |
| False passes and false rejections | New controls cover conflicting result identifiers, disagreement between a REST resource address and its actual resource, mismatched starter report IDs, reassignment of a reviewed section to another subject and extension-only implicit rules. Legal element IDs alongside a supported FHIR primitive now permit evaluation. [Fidelity regressions](tests/test_release_fidelity.py) |
| Partial evaluation | Changing an independently reviewed section still produces a finding with a missing, unreadable or invalid row reference. The suite keeps the unknown row count and the finding. A missing reference alone returns exit 2 and a sanitized diagnostic. The reverse direction preserves known row findings if the narrative fails. [CLI regressions](tests/test_release_cli.py) |
| Corpus replay | All 1,000 unchanged synthetic reports passed. Each of 1,000 deliberately changed reports yielded the right finding on the expected row. The receipt for 18,329 rows and 1,015 pages matched the pinned earlier run byte for byte. [Corpus and mutation breakdown](evidence/starter-results.json) |
| FHIR profile control | The original EU teaching document produced zero fatal issues, zero errors, three warnings and two informational messages using validator 7.0.6, R4 core 4.0.1, EU Lab 2.1.0 and disabled remote terminology. This checks one example under those settings. [Validator, options and warnings](evidence/eu-teaching-results.json) |
| Packaging | The source archive includes the tests and the files they exercise. The wheel includes the offline five-case demo, expected results, schema and notices. The verifier matches the wheel contents against both the source distribution and the checkout before exercising the installed command. It also checks the source archive for local ownership metadata. [Distribution verifier](scripts/verify_distribution.py) |

### Performance and memory

On an arm64 Mac using CPython 3.11.9, the median warm single-report check with explicit bindings for 1,000 rows fell from 22.13 to 14.31 ms. Its traced Python allocation peak fell from 6.29 to 4.55 MB. The comparable suite case fell from 23.15 to 14.43 ms. A fresh-process bound command took 51.09 ms before and 47.13 ms after. All six comparison outputs matched the baseline. These measurements used local files, a warm filesystem cache and 21 runs per scenario. [Measurements and replay command](evidence/performance.json)

The 1,000-row warm check with identifiers already present rose from 10.72 to 13.06 ms. On a 16-row case, starting a fresh process for the bound check rose from 28.47 to 32.45 ms. The benchmark compares complete versions. Retain both controls when changing indexing or startup behavior. [Benchmark harness](scripts/benchmark_check.py)

Across a 3,000-case suite, aggregate-only output used 1.67 MB of peak traced Python allocations versus 4.78 MB for full output. The JSON shrank from 532,426 to 409 bytes with identical aggregate findings, denominators and exit code. The manifest and each active case still occupy memory. [Suite measurements](evidence/suite-summary-performance.json) · [Reproduction script](scripts/benchmark_suite.py)

### Release artifacts and outstanding gates

The local candidate release directory pairs the full source ZIP, source distribution and installable wheel with `VERIFICATION.json` and `SHA256SUMS`. The verification record identifies the exact artifacts, locally tested Python versions, test counts, installed-command checks and archive scan scope. Use `shasum -a 256 -c SHA256SUMS` in that directory before handing it to another team.

1. **Maintainer.** Run the checked-in workflow on hosted Ubuntu, macOS and Windows for the exact revision intended for publication. Archive job URLs and outcomes. The local arm64 macOS tests exercise interpreter compatibility. [Hosted workflow](.github/workflows/test.yml)
2. **Receiving team.** Supply an independently prepared synthetic report, a correct export and an export with one known change. Record which source row changed, whether the finding identified it, and how missing or unsupported cases appeared in the team's CI totals. Add a minimized regression for any discrepancy before stable promotion.
3. **Release owner.** After those checks, select the approved revision, verify its package contents and notices, tag the stable version, build that version and verify its final bytes before publication. Any clinical or terminology claim needs evidence for its exact scope and intended setting.
