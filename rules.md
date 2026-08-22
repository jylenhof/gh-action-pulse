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
=> full exit error on this one !

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
