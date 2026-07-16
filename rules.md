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
=> if exist, sha of newest semver tag meeting `min_age` + comment # tag if date of this tag is newer than actual last commit of this branch, otherwise sha of last commit of this branch + comment # branch

action@branch # branch
=> if exist, sha of newest semver tag meeting `min_age` + comment # tag if date of this tag is newer than actual last commit of this branch, otherwise sha of last commit of this branch + comment # branch

action@branch # bullshit
=> if exist, sha of newest semver tag meeting `min_age` + comment # tag if date of this tag is newer than actual last commit of this branch, otherwise sha of last commit of this branch + comment # branch

action@sha
=> if existing sha is related to a tag, sha of newest semver tag meeting `min_age` + comment # tag
=> if not, find latest sha in all branches related to this commit sha + comment # branch

action@sha # tag
=> sha of newest semver tag meeting `min_age` and >= pinned tag
  (if pinned tag is too young and no newer eligible tag exists, keep pinned tag)

action@sha # branch
=> if exist sha of newest semver tag meeting `min_age` + comment # tag if date of this tag is newer than actual date of this commit sha, otherwise find latest sha of this branch + comment # branch

action@sha # bullshit
=> if existing sha is related to a tag, sha of newest semver tag meeting `min_age` + comment # tag
=> if not, find latest sha in all branches related to this commit sha + comment # branch

action@bullshit
=> full exit error on this one !
