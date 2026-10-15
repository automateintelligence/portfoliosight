# Gate change: builds on four CPUs (parallel ladders)

Date: 2026-10-15. For the owner and the coordinator.

Instruction (the owner, relayed by the coordinator): make a tensor build use more CPUs so
100-fund admin menus become practical; raise the API and nightly containers from `cpus: "2"` to
`cpus: "4"`; update and re-freeze any frozen gate test the change makes false.

## What changed in the product that the gate reads

- `deploy/docker-compose.yml`: `api` and `nightly` limits `cpus: "4"` (were `"2"`); memory,
  reservations and everything else unchanged.
- Engine: the ladders, the peak search's own starts and the frontier programs run on worker
  processes (`portfoliosight/engine/parallel.py`, new). The tensor bytes are unchanged: the
  pinned UI fixture and the fixture tensor are identical for 1, 2, 3, 4 and 8 workers.

## Every gate file changed

| Gate file | Assertion, leg | Before | After | Property it protects | Why the new form is not weaker |
|---|---|---|---|---|---|
| `tests/test_a_ps_32_image_repo_compose_hygiene.py` | A-PS-32, compose leg | api `cpus` in `("2", "2.0")` | api `cpus` in `("4", "4.0")` | The service on a shared host has a hard CPU cap | Still an exact hard limit; the number follows the owner's decision. Memory, reservations, port, volume and env checks are untouched. |
| `manifest.yaml` | A-PS-32 claim | "sets cpus 2" | "sets cpus 4" | Claim text matches the test | Text only. |

`docs/specs/2026-10-13-portfoliosight-demo-design.assertions.md` (the assertions source) carries
the same change in the A-PS-32 claim.

## Left as they are, on purpose

- A-PS-25 (engine pure and fully covered): true as written. The new engine module
  `parallel.py` imports nothing the scan forbids and is fully covered; reading the host's CPU
  allowance (`/sys/fs/cgroup/cpu.max`, the affinity mask, `PS_BUILD_WORKERS`) lives outside the
  engine, in `portfoliosight/cpus.py`.
- Every other assertion: the tensor bytes did not change, so nothing that reads a tensor moved.
