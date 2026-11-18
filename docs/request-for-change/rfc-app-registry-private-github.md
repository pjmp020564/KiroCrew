---
title: App registry sources in private GitHub repositories, read through the host's GitHub CLI sign-in
status: draft
author: buluoray
created: 2026-11-17
last-audited: 2026-11-17
audited-at: 0e618612ac5
doc-pr: null
implementation-prs: []
tracking-issues: [38988]
supersedes: []
superseded-by: []
---

# RFC: App registry sources in private GitHub repositories

- Status: draft. Nothing is on main. Verified at `0e618612ac5`.
- Scope: the App Store's external registries and the apps they list, when the
  repository is a private `https://github.com/<owner>/<repo>` repository.

## Summary

A user who adds a registry that lives in a private GitHub repository gets
"sign-in refused" today, even when the GitHub CLI (`gh`) on the computer that
runs Kiro Crew is signed in with access to that repository. This RFC lets the
registry read such a repository through `gh`, without Kiro Crew ever seeing the
GitHub token. Anonymous access, and the user's own git credentials, are tried
first. `gh` is used only when that fails, only for repositories the owner
designated, and every check a public source gets still applies.

## Motivation

### How sources are fetched today

Every registry source is a git repository and every fetch is a `git` command.
Nothing downloads raw files, release assets or tarballs.

- The registry index is a shallow `git clone` of the configured repository
  (`_fetch_external_registry_index`, `apps/registry_pipeline/indexes.py`). It
  reads `app-registry.json`, or scans `apps/*/app.json` when there is none.
- An app's card details come from a shallow clone of the app's repository
  (`_fetch_app_manifest`, `apps/registry_pipeline/manifests.py`), cached under
  the manifest cache.
- Install and update clone, fetch or pull into the app source directory
  (`_git_clone_or_pull` and `_git_fetch_ref`,
  `apps/registry_pipeline/checkout.py`).
- Integrity: a pinned app is fetched by commit and the checkout must report that
  exact commit (`_git_fetch_ref`, "pinned commit verification failed"). An
  existing checkout is reused only when its `origin` is the same repository and
  branch. Admission (`apps/admission.py`) judges the cloned `app.json`. Hooks,
  fsmonitor, submodules and `ext::` are turned off on every git spawn.
- Credentials follow who chose the repository. Index-chosen repositories run
  with `anonymous_git_env()` and the strict sandbox, so an untrusted index
  cannot make Kiro Crew read a private sibling repository with the owner's
  identity. The configured index repository, apps in that same repository
  (`_is_owner_designated_repo`), and `owner`-tier registries use
  `minimal_env()`, which keeps the owner's git config and credential helpers.
- Failures reach the dashboard as a fixed cause (`dns`, `host_key`, `auth`,
  `network`, `timeout`, `other`, in `git_targets.py`), and
  `website/src/components/appstore/registryRefreshMessage.ts` turns each into a
  remedy sentence.

### The problem

An `https://` clone runs in the `strict` sandbox, which hides `~/.config/gh`.
A user who signed in with `gh auth login` and `gh auth setup-git` has a git
credential helper that calls `gh`, but inside the sandbox that `gh` cannot read
its own sign-in. The clone fails and the user sees "sign-in refused", with no
way to fix it from the dashboard. The users this matters for have no terminal,
so "configure a credential helper" is not an answer either.

## Goals

1. A registry index, its card details and its apps can come from a private
   GitHub repository the host's `gh` can read.
2. Kiro Crew never reads, copies, logs or stores the GitHub token. It never runs
   `gh auth token`. `gh` hands the credential to `git` itself.
3. Every integrity check that applies to a public source applies unchanged.
4. When `gh` is missing, signed out, or has no access, the dashboard says so
   and says what to do. Nothing falls back silently. Nobody is asked to paste a
   token.
5. Nothing new to configure. Adding a private registry works from the existing
   Add Registry form.

## Non-goals

- GitHub Enterprise Server hosts. Only `github.com` in this RFC.
- A "this source is private" setting. Trying anonymous first, then `gh`, needs
  no new config key, so no persisted format changes.
- Letting an untrusted index reach private sibling repositories. Index-chosen
  repositories stay anonymous; see Security.
- Downloading tarballs or release assets. See Alternatives.

## Design

### When `gh` is used

`gh` is a second attempt, never the first. A fetch takes it only when all of
these hold:

1. The fetch already runs with the owner's credentials today: the configured
   index repository, an app in that same repository, or an install the
   `owner` tier confirms. An index-originated (anonymous) fetch never does.
2. The URL is exactly `https://github.com/<owner>/<repo>` (optionally `.git`),
   with no user info, port, query or fragment. `owner` matches
   `^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$`, `repo` matches `^[A-Za-z0-9._-]{1,100}$`
   and is not `.` or `..`. Anything else is refused before any process starts.
3. The first attempt failed for a reason that is not the network: its cause is
   `auth` or `other`. A `dns`, `network`, `timeout` or `host_key` failure is
   reported as it is today.

### What runs

All `gh` commands are argv lists with no shell, a timeout, and the hardened
runner in `kiro_crew/github_runner.py` (validated absolute binary, `gh_env()`,
audit event before each spawn):

1. `resolve_gh()` finds a trusted `gh`. None found: cause `gh_missing`.
2. `gh auth status --hostname github.com`. Non-zero exit: cause `gh_signed_out`.
3. `gh api repos/<owner>/<repo> --silent`. Non-zero exit: cause `gh_no_access`
   (GitHub answers 404 for a private repository the account cannot read).
4. The same git fetch runs again, through the split path `_git_fetch_ref`
   already uses for credentialed fetches: only the network `git fetch` gets the
   credential; `init`, `checkout` and `branch` run without it. For that one
   network step:
   - the git config gets `credential.helper=` (which clears every helper set
     before it) and then `credential.helper=!'<validated gh path>' auth
     git-credential`, through `GIT_CONFIG_*` variables, never argv;
   - the sandbox tier is `standard` instead of `strict`, so `gh` can read
     `~/.config/gh` and the system keyring;
   - the output is reduced to fixed labels, as for any credentialed fetch.

   git runs a `!` helper through `sh -c`. The string is fixed text plus the
   validated absolute path quoted with `shlex.quote`; no repository, index or
   user value is in it.

Updates of an installed private app take the same path. Because a credentialed
pull inside an app checkout is already refused, the existing move-aside and
fresh-fetch path runs, as it does for a URL with embedded credentials.

### Integrity

The second attempt is the same git fetch with a different credential. So the
pinned-commit check, the origin and branch checks, admission of the cloned
`app.json`, containment of `subdirectory`, the hook and submodule switches, the
host trust gate (`is_clone_host_trusted`) and the app cache paths are all the
same code as for a public source. Nothing is unpacked from an archive, so no new
path-traversal surface appears.

### What the user sees

Three new fetch causes join the fixed set: `gh_missing`, `gh_signed_out`,
`gh_no_access`. The registry status and the refresh result carry `repo` as
`owner/repo` next to `host` for these causes. The dashboard shows one sentence
per cause, for example:

> Sign in to GitHub CLI on the computer that runs Kiro Crew, with an account
> that can read acme/apps. Kiro Crew uses that computer's GitHub sign-in, not
> yours.

The second sentence matters for shared and remote crews, where the person
looking at the page is not at the gateway's computer. An install that fails
for these reasons returns the same sentence in `error` and the cause in `code`.

## Migration plan

One implementation PR, after this RFC is accepted.

- Phase 1: the gh second attempt for index fetch, card details, install and
  update; the three causes; dashboard sentences in every shipped language.
  Exit criteria, each a unit test with `gh` mocked:
  - a private index fetch that fails anonymously succeeds through `gh`, and the
    `gh` network step's env holds the helper config and no token;
  - `gh` missing, signed out, and 404 with `gh` each record their cause and
    never run the second git fetch;
  - a pinned install of a private app whose fetched commit differs from the pin
    is refused, exactly as for a public app;
  - an owner or repo name with shell characters, a port, or user info is
    refused before any process starts;
  - an index-originated install never calls `gh`;
  - the dashboard renders the sign-in sentence with `owner/repo`.

## Backward compatibility

No config key, file format or route changes. A public registry takes the same
path as today. The cause set grows by three values; an older dashboard reads an
unknown cause as `other` and shows its plain line.

## Security considerations

- Token: Kiro Crew starts `gh`, and git starts `gh` as its credential helper.
  The token passes from `gh` to `git` over the credential protocol pipe. It is
  never in Kiro Crew's memory, argv, logs, caches or receipts.
- Confused deputy: the anonymous rule for index-chosen repositories is kept. A
  private index can list apps in its own repository (same-repo rule) and, for an
  `owner`-tier registry, elsewhere; any other private repository it names still
  fails, and the dashboard shows the plain failure.
- Sandbox: only the network `git fetch` step moves from `strict` to `standard`.
  That step runs no repository code: hooks and fsmonitor are off and checkout
  is a separate step without the credential.
- Fail closed: any `gh` error, a timeout, or a failed audit write ends the fetch
  with a cause. No path goes back to an unchecked source.
- No listener, route or storage exposure changes.

## Alternatives considered

- **Download a tarball with `gh api repos/<o>/<r>/tarball/<sha>`.** No git
  credential at all, but the tree is no longer a git checkout. The pinned-commit
  check would trust the server's word for the commit instead of git's object
  check, updates would need a second code path, and unpacking adds archive
  traversal risk. That is less checking for private sources, which Goal 3 rules
  out.
- **`gh repo clone`.** Runs git with the same `gh` credential helper, but
  outside Kiro Crew's split fetch, so checkout would run with the credential and
  without the hook switches.
- **Expose `~/.config/gh` to every https clone.** Simpler, but it would give the
  owner's GitHub sign-in to index-chosen clones too, which reopens the confused
  deputy hole.
- **Ask the user for a token.** Rejected by Goal 2 and Goal 4.

## Open questions

- Should GitHub Enterprise Server hosts follow, keyed on the hosts `gh auth
  status` reports? Left for a later RFC.
