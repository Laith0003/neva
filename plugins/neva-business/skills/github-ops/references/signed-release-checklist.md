<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. Generalized from the upstream maintainer release checklist. -->

# Signed Release Checklist

Use this for any repository whose release must prove that the Git tag, the published package, the GitHub Release and the announcement all describe the same verified artifact. Every mutation below (tag push, publish, dist-tag change, release creation, announcement) waits for an explicit yes from the user.

## Non-negotiable invariants

- Never move, recreate or reuse a published tag. A bad release gets a new patch version.
- The release tag is a signed annotated tag on the exact green commit of the default branch.
- Publish only the archive that the release workflow packed and verified. Never publish different bytes under the same version.
- Any registry lookup failure other than "not found" blocks the release.
- Do not manually promote a dist-tag such as `latest` or replace release assets after the fact.
- Release notes describe shipped behavior only, never future plans.

## 1. Reconfirm the release surface

```bash
git fetch origin main --tags
git switch main
git pull --ff-only origin main
git status --short          # must be empty
git rev-parse HEAD          # must equal the next line
git rev-parse origin/main
gh run list --branch main --limit 10
gh pr list --state open --limit 20
```

Stop if `HEAD` differs from `origin/main`, any required check on that commit is red or pending, or an open release-surface PR changes the patch contents.

## 2. Confirm the version is unused

```bash
VERSION=<next-version>
git ls-remote --tags origin "refs/tags/v${VERSION}*"   # expect nothing
gh release view "v${VERSION}"                          # expect not found
npm view "<package>@${VERSION}" version                # expect E404 (or the registry's not-found)
```

## 3. Land a reviewed version-prep change

- Branch from exact `main`, bump the version, add reviewed release notes and a runbook if the project keeps one.
- Merge through the normal review path. Do not use a script that commits, tags and pushes in one step: it skips the merge, green main, signed tag boundary.
- The operator needs a local signing identity before tagging. Token-based GitHub access alone is not enough.

## 4. Wait for exact main to turn green again

After the prep merge, the new `main` commit is the only commit you may tag. Re-run the step 1 checks.

## 5. Create and push the signed tag (approval required)

```bash
git tag -s "v${VERSION}" -m "<project> ${VERSION}" HEAD
git tag -v "v${VERSION}"                # must verify locally before push
git push origin "refs/tags/v${VERSION}"
```

Required proof: clean worktree, `HEAD == origin/main`, and `git tag -v` succeeds.

## 6. Watch the release workflow

A trustworthy release workflow should: prove the tag commit equals `origin/main`, validate version and manifests, pack one archive and record its SHA-256, test that exact archive on every supported OS, publish with provenance under a staging dist-tag, read back the registry integrity and compare it to the tested archive, promote to `latest` only after that match, and create the GitHub Release from the reviewed notes.

## 7. Public readback and canaries

```bash
npm view <package> dist-tags --json
npm view "<package>@${VERSION}" name version dist.integrity --json
gh release view "v${VERSION}" --json tagName,name,isDraft,isPrerelease,publishedAt,url
gh api repos/{owner}/{repo}/releases/latest --jq .tag_name
npx --yes "<package>@${VERSION}" --help
```

Run the install, doctor, repair, uninstall and rollback canaries from the runbook if the project has them.

## 8. Announcement

Announcements are public posts: draft them, show the exact text and channel, and publish only after an explicit yes. Record the announcement URL as evidence.
