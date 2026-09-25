# Rules used to determine actual recommendation

action@tag
=> sha of newest semver tag meeting `min_age` and >= pinned tag
  (if no newer eligible tag exists, keep pinned tag to avoid downgrade)

action@tag # tag
=> sha of newest semver tag meeting `min_age` and >= pinned tag
  (if pinned tag is too young and no newer eligible tag exists, keep pinned tag)

action@tag # bullshit
=> sha of newest semver tag meeting `min_age` and >= pinned tag
  (if no newer eligible tag exists, keep pinned tag to avoid downgrade)

action@branch
=> if exist, sha of newest semver tag meeting `min_age` + comment # tag if date of this tag is newer than or equal to the last commit of this branch, otherwise sha of last commit of this branch + comment # branch

action@branch # branch
=> if exist, sha of newest semver tag meeting `min_age` + comment # tag if date of this tag is newer than or equal to the last commit of this branch, otherwise sha of last commit of this branch + comment # branch

action@branch # bullshit
=> if exist, sha of newest semver tag meeting `min_age` + comment # tag if date of this tag is newer than or equal to the last commit of this branch, otherwise sha of last commit of this branch + comment # branch

action@sha
=> if existing sha is related to a tag, sha of newest semver tag meeting `min_age` + comment # tag
=> if not, find latest sha in all branches related to this commit sha + comment # branch

action@sha # tag
=> sha of newest semver tag meeting `min_age` and >= pinned tag
  (if pinned tag is too young and no newer eligible tag exists, keep pinned tag)

action@sha # branch
=> if exist sha of newest semver tag meeting `min_age` + comment # tag if date of this tag is newer than or equal to the actual date of this commit sha, otherwise find latest sha of this branch + comment # branch

action@sha # bullshit
=> if existing sha is related to a tag, sha of newest semver tag meeting `min_age` + comment # tag
=> if not, find latest sha in all branches related to this commit sha + comment # branch

action@bullshit
=> full exit error on this one (exit code 6): every invalid reference is reported with the
  action name, the reference and the `file:line` where it is used

## Version tags

"semver tag" above means a tag whose name, without a leading `v`, is a valid SemVer version
(`v1.2.3`, `1.2.3-rc.1`). This is the recommended way of tagging an action.

When a repository has no SemVer tag at all, non-SemVer version tags are used instead with the
same rules (`min_age`, no downgrade, ...), and a warning is emitted. Accepted names are an optional
`v`/`V`, one to three numeric components and an optional `-prerelease` suffix
(`v1`, `v0.6`, `1.2`, `v2-beta`); missing components count as `0`. SemVer tags always win: as
soon as one SemVer tag exists, non-SemVer version tags are ignored.

## Degraded mode (no usable semver tag)

When the rules above cannot produce a recommendation (no version tag, no tag old enough for
`min_age`, a tag or branch that no longer exists, ...), the run does not stop: a warning is
emitted, the action is listed in the "Degraded recommendations" table, and the best fallback
is used, always pinning a SHA when possible:

1. a tag is currently pinned (`action@tag`, `action@sha # tag`, or `action@sha` pointing at a tag)
=> sha of that tag + comment # tag
  (for `action@sha`, the most precise version-like tag at that sha is chosen, e.g. `v1.2.0` over `v1`)
2. otherwise, a branch is pinned (`action@branch`, `action@sha # branch`)
=> sha of last commit of this branch + comment # branch
3. otherwise, for `action@sha`
=> find latest sha in all branches related to this commit sha + comment # branch
4. otherwise
=> keep the `uses:` line unchanged

`action@bullshit` (a reference that exists neither as a branch, a tag nor a commit) still
stops the run, as stated above.

Freshness (`max-age`) is checked against the selected version tag, SemVer or not. When no version
tag exists at all, freshness cannot be verified and the action is reported as stale
(use `ignore[max-age]` on that line to accept it).

Extra `#` comments after the first trailing comment (for example `gh-action-pulse: ignore[max-age]`)
are preserved when rewriting a `uses:` line. If the first comment is a tag or branch, it is
updated to the recommended description; otherwise the recommended description is inserted
in front of the existing comments.

A `gh-action-pulse: ignore[max-age]`, `ignore[min-age]`, and/or `ignore[nodejs-version]` hint on that
line applies to that action (quoted ids such as `ignore["max-age"]` are also accepted).
`ignore[max-age]` and `ignore[nodejs-version]` skip the matching fail-check.
`ignore[min-age]` recommends the newest SemVer tag without waiting for `min_age`.
Unknown check ids are reported and do not skip a check.

A `gh-action-pulse: override[max-age=200]`, `override[min-age=3]`, and/or
`override[nodejs-version=20]` hint on that line changes the matching threshold
(quoted assignments such as `override["max-age"=200]` are also accepted).
Several assignments can be comma-separated inside the brackets.
`ignore[...]` for the same check on the same line takes precedence.
Unknown keys and out-of-range values are reported and not applied.

action@sha # tag # extra
=> sha of newest semver tag meeting `min_age` and >= pinned tag, preserving extra comments

action@sha # extra
=> if existing sha is related to a tag, sha of newest semver tag meeting `min_age` + comment # tag # extra
=> if not, find latest sha in all branches related to this commit sha + comment # branch # extra

action@sha # tag # gh-action-pulse: ignore[max-age]
=> same recommendation as `action@sha # tag`, with the max-age freshness check skipped

action@sha # tag # gh-action-pulse: ignore[min-age]
=> sha of newest semver tag >= pinned tag, without waiting for `min_age`

action@sha # tag # gh-action-pulse: override[max-age=200]
=> same recommendation as `action@sha # tag`, with the max-age freshness limit set to 200 days

action@sha # tag # gh-action-pulse: override[min-age=3]
=> sha of newest semver tag meeting a 3-day wait and >= pinned tag
