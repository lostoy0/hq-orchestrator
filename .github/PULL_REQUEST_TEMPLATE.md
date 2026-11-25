## 改动 / Change

<!-- 改了什么、为什么 / what changed and why -->

## 检查 / Checklist

- [ ] 自测全部通过 / self-tests pass（`for t in tests/test_*.sh; do bash "$t"; done` + `python3 -m unittest discover tests`）
- [ ] 改了行为就在 `CHANGELOG.md` 加了五项条目 / behavior changes have a five-field `CHANGELOG.md` entry
- [ ] 中英文 README 已同步 / `README.md` and `README.en.md` are in sync
- [ ] 没在真实宿主上跑过的适配，文档里写了“未实机运行” / unverified adapters are marked "not run on a real host"
- [ ] 我同意 [CONTRIBUTING.md](../CONTRIBUTING.md) 里的贡献条款 / I agree to the contribution terms in CONTRIBUTING.md
