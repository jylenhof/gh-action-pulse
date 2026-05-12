# Rules used to determine actual recommendation

action@tag
=> sha of last semver tag + comment # tag

action@tag # tag
=> sha of last semver tag + comment # tag

action@tag # bullshit
=> sha of last semver tag + comment # tag

action@branch
=> if exist, sha of last semver tag + comment # tag if date of this tag is newer than actual last commit of this branch, otherwise sha of last commit of this branch + comment # branch

action@branch # branch
=> if exist, sha of last semver tag + comment # tag if date of this tag is newer than actual last commit of this branch, otherwise sha of last commit of this branch + comment # branch

action@branch # bullshit
=> if exist, sha of last semver tag + comment # tag if date of this tag is newer than actual last commit of this branch, otherwise sha of last commit of this branch + comment # branch

action@sha
=> if existing sha is related to a tag, sha of last semver tag + comment # tag
=> if not, find latest sha in all branches related to this commit sha + comment # branch

action@sha # tag
=> sha of last semver tag + comment # tag

action@sha # branch
=> if exist sha of last semver tag + comment # tag if date of this tag is newer than actual date of this commit sha, otherwise find latest sha of this branch + comment # branch

action@sha # bullshit
=> if existing sha is related to a tag, sha of last semver tag + comment # tag
=> if not, find latest sha in all branches related to this commit sha + comment # branch

action@bullshit
=> full exit error on this one !
