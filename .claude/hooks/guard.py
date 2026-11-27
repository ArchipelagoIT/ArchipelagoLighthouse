#!/usr/bin/env python3
"""PreToolUse guard for Policy SEN-SEC-POL-001. Standard library only; works on Python 3.9+.

Exit 0 = allow. Exit 2 = block (stderr is shown to Claude).
Printing a JSON "ask" decision on stdout (exit 0) makes Claude Code ask the user.
Any unexpected error BLOCKS (fail closed): Claude Code treats exit 1 as "allow".

This is a SEATBELT, not a lock. It parses shell commands and matches patterns, so a
determined program (for example a script the agent writes and then runs) can get past it.
The real protections are outside the agent: no production write credentials on dev
machines, GitHub branch protection + CODEOWNERS, and Claude Code managed settings / sandbox.
Edit this file by hand only (the agent is blocked from changing it).
Tests: python3 .claude/hooks/test_guard.py
"""
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
import time

POLICY = "SEN-SEC-POL-001"

# Claude Code allows a command when this hook times out (10 s), so the guard keeps its own budget
# and blocks anything it cannot check well inside it.
START = time.monotonic()
GIT_DEADLINE = 5.0          # seconds for all git lookups together
MAX_COMMAND_BYTES = 16384
MAX_SEGMENTS = 200

# MCP tools that may run without asking, by exact name. Humans add entries here.
MCP_ALLOW = set()


class Blocked(Exception):
    pass


def block(reason):
    raise Blocked(reason)


def ask(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": "%s: %s" % (POLICY, reason),
    }}))
    sys.exit(0)


# =====================================================================================
# Secret and protected paths
# =====================================================================================
HOME = os.path.expanduser("~").lower().rstrip("/")
PROJECT = (os.environ.get("CLAUDE_PROJECT_DIR") or "").lower().rstrip("/")
SAFE_ENV = {".env.example", ".env.sample", ".env.template"}
SECRET_EXT = (".pem", ".key", ".p8", ".p12", ".pfx", ".jks", ".keystore", ".mobileprovision")
SECRET_NAMES = {"id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", "credentials", "service-account.json",
                "google-services.json", "googleservice-info.plist", "key.properties",
                ".netrc", ".git-credentials", ".pgpass", ".pypirc", ".vault-token",
                "credentials.tfrc.json", "pub-credentials.json"}
SECRET_NAME_RE = re.compile(r"^service-account.*\.json$")
ANYWHERE_SECRET_DIRS = ("/.aws/", "/.ssh/", "/.gnupg/")
# Keep in step with sandbox.filesystem.denyRead in settings.json: the sandbox only covers Bash,
# so for Claude's Read/Grep/Edit tools this list is the only check.
HOME_SECRET_DIRS = ("/.kube/", "/.docker/", "/.config/gh/", "/.config/gcloud/", "/.config/op/", "/.azure/",
                    "/.npmrc", "/.config/git/credentials", "/.gradle/gradle.properties", "/.yarnrc.yml",
                    "/.claude.json", "/.zsh_history", "/.bash_history", "/library/keychains/")
# Names that are secrets as files but common as folder or package names in code.
BASH_NAME_EXCEPTIONS = {"credentials"}
# Paths the agent may not change from the shell (guard rails, git behaviour, MCP servers).
PROTECTED = (".claude", ".git/config", ".git/hooks", ".mcp.json", ".git/commondir", ".git/worktrees",
             ".git/modules")


def secret_path(p, for_bash=False):
    raw = p.replace("\\", "/").lower()
    p = os.path.expanduser(raw).lower()
    base = p.rstrip("/").split("/")[-1]
    if base.startswith(".env") and base not in SAFE_ENV:
        return True
    if base.endswith(".env") and base not in SAFE_ENV and len(base) > 4 and \
            base not in ("process.env", "import.meta.env", "deno.env", "bun.env"):   # config.env, prod.env
        return True
    probe = "/" + p.lstrip("/") + "/"
    if any(d in probe for d in ANYWHERE_SECRET_DIRS):
        return True
    if raw.startswith("~/") or (HOME and p.startswith(HOME + "/")):
        rel = "/" + p[len(HOME):].lstrip("/") if p.startswith(HOME) else probe
        if any((rel + "/").startswith(d) or (rel + "/").startswith(d.rstrip("/") + "/") for d in HOME_SECRET_DIRS):
            return True
    # Root-level secrets/ folder only (not backend/internal/secrets/ packages).
    if raw.startswith(("secrets/", "./secrets/")) or (PROJECT and p.startswith(PROJECT + "/secrets/")):
        return True
    if base.endswith(SECRET_EXT) and base not in SECRET_EXT:     # "server.key", but not jq's ".key"
        return True
    if base in SECRET_NAMES and not (for_bash and base in BASH_NAME_EXCEPTIONS):
        return True
    if SECRET_NAME_RE.match(base):
        return True
    return False


def under_claude(p):
    return "/.claude/" in "/" + p.replace("\\", "/").lower().strip("/") + "/"


def guard_rail_path(p, cwd=""):
    """True for .claude/settings*, .claude/hooks/, .git/config, .git/hooks/, .mcp.json (also via symlinks)."""
    candidates = [p]
    try:
        full = p if os.path.isabs(os.path.expanduser(p)) else os.path.join(cwd or os.getcwd(), p)
        candidates += [os.path.normpath(full), os.path.realpath(full)]
    except Exception:
        pass
    try:
        candidates.append(os.path.expanduser(p))
    except Exception:
        pass
    home = HOME.rstrip("/")
    for c in candidates:
        norm = "/" + os.path.normpath(c.replace("\\", "/")).lower().lstrip("/")
        if ("/.claude/settings" in norm or "/.claude/hooks/" in norm or norm.endswith(("/.claude/hooks", "/.claude"))
                or norm.endswith(("/.git/config", "/.git/config.worktree", "/.git/commondir"))
                or "/.git/hooks/" in norm or "/.git/worktrees/" in norm or "/.git/modules/" in norm
                or norm.endswith("/.mcp.json")):
            return True
        # Git config outside the project: it can add aliases, hooks and URL rewrites for every repo.
        if home and (norm == home + "/.gitconfig" or norm.startswith(home + "/.config/git/")):
            return True
    return False


def mentions_protected(t):
    """Does a shell word name a protected path, literally or through a wildcard in any part?"""
    tl = t.lower()
    if any(x in tl for x in PROTECTED):
        return True
    if any(ch in t for ch in "*?["):
        parts = [x for x in t.split("/") if x]
        for i, part in enumerate(parts):
            if part[:1] in (".", "[") and any(ch in part for ch in "*?[") and \
                    (fnmatch.fnmatch(".claude", part) or fnmatch.fnmatch(".mcp.json", part)):
                return True
            if part.lower() == ".git" and i + 1 < len(parts) and \
                    any(fnmatch.fnmatch(x, parts[i + 1]) for x in ("config", "hooks")):
                return True
    return False


# =====================================================================================
# Shell parsing
# =====================================================================================
OPERATORS = {";", "&", "&&", "|", "||", "|&", ";;", "(", ")", "\n"}
REDIRECTS = {">", ">>", ">|", "<>", "&>", "&>>", ">&", "<", "<<", "<<<", "<&"}
WRITE_REDIRECTS = {">", ">>", ">|", "<>", "&>", "&>>", ">&"}
# "$" (before "(") and "`" stay in the outer segment so its checks see an expansion there;
# the command inside $(...) or `...` is then checked as its own segment.
SUBST_MARKS = {"$", "`"}


def tokenize(cmd):
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=";&|()<>\n`")
        lex.whitespace = " \t\r"
        lex.whitespace_split = True
        lex.commenters = ""
        return list(lex)
    except ValueError:
        # Unbalanced quotes (often heredoc bodies). Fall back to a rough split.
        return [t for t in re.split(r"[\s'\"]+|([;&|()<>`\n])", cmd) if t]


def segments(tokens):
    """Split tokens into simple commands. Redirect operators stay inside their segment."""
    seg = []
    for t in tokens:
        if t in SUBST_MARKS:
            seg.append(t)
            if t == "`":
                yield seg
                seg = []
            continue
        if t in OPERATORS or (t and set(t) <= set(";&|()\n") and t not in REDIRECTS):   # '' is an argument
            if seg:
                yield seg
            seg = []
        else:
            seg.append(t)
    if seg:
        yield seg


WRAPPERS = {"sudo", "doas", "command", "exec", "nohup", "time", "nice", "xargs", "builtin",
            "timeout", "caffeinate", "stdbuf", "unbuffer", "arch"}
ENV_OPT_WITH_VALUE = {"-u", "--unset", "-C", "--chdir", "-S", "--split-string", "-P"}


def unwrap(argv):
    """Drop VAR=value prefixes and wrappers (sudo, env VAR=1, xargs ...). Returns argv or []."""
    i = 0
    while i < len(argv):
        a = argv[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", a):
            i += 1
            continue
        base = os.path.basename(a)
        if base in WRAPPERS:
            i += 1
            while i < len(argv) and argv[i].startswith("-"):
                i += 1
            if base == "timeout" and i < len(argv) and re.match(r"^\d", argv[i]):
                i += 1
            continue
        if base == "env":
            j = i + 1
            while j < len(argv) and (argv[j].startswith("-") or "=" in argv[j]):
                j += 2 if argv[j] in ENV_OPT_WITH_VALUE else 1
            if j >= len(argv):
                return argv[i:]          # env with no command: an environment dump, keep it
            i = j
            continue
        break
    return argv[i:]


def prog(argv):
    return os.path.basename(argv[0]).lower() if argv else ""


def has_expansion(t):
    return "$" in t or "`" in t


# =====================================================================================
# Rule data
# =====================================================================================
TEXT_RULES = [
    # Rough text checks that also catch heredocs and code passed to interpreters.
    (r"(^|[\s/'\"=<>:])\.env(?!\.(example|sample|template)\b)(\.[\w.-]+)?(?=$|[\s'\";|&)>:/])",
     "reading or writing .env files from the shell is not allowed. "
     "The developer creates .env by hand (cp .env.example .env)."),
    (r"(^|[\s/'\"=~:])\.(aws|ssh|gnupg)(/|\b)", "access to ~/.aws, ~/.ssh or ~/.gnupg is not allowed."),
    (r"~/\.(kube|docker|config/gh|config/gcloud|azure|npmrc|netrc|pgpass|git-credentials)\b",
     "access to credential files in your home folder is not allowed."),
    (r"\.(pem|p12|pfx|jks|keystore)\b", "access to key or keystore files is not allowed."),
    (r"\bsecurity\s+(find|dump)-(generic-password|internet-password|keychain)\b",
     "reading the macOS keychain is not allowed."),
    (r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z|da|k)?sh\b", "piping downloads into a shell is not allowed."),
    (r"(\$home|\$\{home\})/\.(kube|docker|config/gh|config/gcloud|azure|npmrc|netrc|pgpass|git-credentials)\b",
     "access to credential files in your home folder is not allowed."),
    # Brace expansion hides dotfile names from every other check (.cl{a..a}ude, .{e..e}nv).
    (r"(^|[\s/'\"=<>:~])\.[\w.-]*\{[^}\s]*(,|\.\.)[^}\s]*\}", "brace expansion on dotfile paths is not allowed."),
    # Settings that change what git push does, passed through the environment.
    (r"\bgit_(config|config_count|config_key_\d+|config_value_\d+|config_parameters|config_global|"
     r"config_system|dir|work_tree|ssh|ssh_command|exec_path|askpass|namespace)\s*=|--config-env\b",
     "changing git settings through environment variables or --config-env is not allowed."),
    (r"\brm\s+-[a-z]*r[a-z]*\s+(/|~|\$home|\.\.)(\s|/?$)", "recursive delete of /, ~ or .. is not allowed."),
]

ENV_READ = re.compile(r"\bos\.environ\b|\.environ\b|\bos\.getenv\b|\bgetenv\b|\bprocess\.env\b|\benv::var|"
                      r"\bENV\[|\bENV\.(to_h|fetch)\b|%ENV\b|\$ENV\b|\bENVIRON\b|\bSystem\.getenv\b|"
                      r"\bDeno\.env\b|\bBun\.env\b|^env$|\benv\s*\|", re.I)
WRITE_PROGS = {"cp", "mv", "rm", "rmdir", "ln", "install", "rsync", "truncate", "dd", "chmod", "chown",
               "chflags", "touch", "unlink", "patch", "tee", "ruby", "node", "deno", "bun", "perl", "php",
               "osascript", "vi", "vim", "nvim", "nano", "emacs", "ed", "ex", "tar", "unzip", "ditto",
               "trash", "srm", "shred", "mkdir", "curl", "wget"}
INTERPRETER = re.compile(r"^(python[\d.]*|pypy[\d.]*|ruby[\d.]*|node[\d.]*|perl[\d.]*|php[\d.]*|"
                         r"bash|sh|zsh|dash|ksh|fish|osascript|swift|lua[\d.]*|tclsh|R|Rscript)$")
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish"}
GIT_TREE_WRITE = {"checkout", "restore", "reset", "stash", "apply", "am", "mv", "rm", "clean", "switch",
                  "merge", "rebase", "pull", "cherry-pick", "revert", "read-tree", "update-index",
                  "worktree", "sparse-checkout", "checkout-index", "filter-branch", "filter-repo"}
# Write commands whose targets cannot be seen from the command line.
UNKNOWN_TARGET_GIT = {"apply", "am"}           # patch files from outside git history
BRANCH_CHANGE_GIT = {"checkout", "switch", "symbolic-ref", "update-ref", "branch", "reset", "rebase"}
GIT_OPT_WITH_VALUE = {"-c", "-C", "--git-dir", "--work-tree", "--namespace", "--config-env",
                      "--exec-path", "--super-prefix"}
GIT_DANGEROUS_CONFIG = re.compile(r"^(alias\.|remote\..+\.(push|mirror|pushurl)$|push\.|core\.hookspath$|"
                                  r"core\.sshcommand$|core\.fsmonitor$|include\.|includeif\.)", re.I)
GIT_BUILTINS = {
    "add", "am", "annotate", "apply", "archive", "bisect", "blame", "branch", "bundle", "cat-file",
    "check-ignore", "check-attr", "checkout", "cherry", "cherry-pick", "clean", "clone", "commit", "config",
    "count-objects", "describe", "diff", "diff-tree", "difftool", "fetch", "for-each-ref", "format-patch",
    "fsck", "gc", "grep", "help", "init", "log", "ls-files", "ls-remote", "ls-tree", "merge", "merge-base",
    "mergetool", "mv", "notes", "pull", "push", "range-diff", "rebase", "reflog", "remote", "repack",
    "replace", "restore", "rev-list", "rev-parse", "revert", "rm", "shortlog", "show", "show-ref",
    "sparse-checkout", "stash", "status", "submodule", "switch", "symbolic-ref", "tag", "update-index",
    "version", "whatchanged", "worktree", "lfs", "maintenance", "read-tree", "checkout-index", "var",
    "verify-commit", "verify-tag", "name-rev", "hash-object", "write-tree", "commit-tree", "update-ref",
    "filter-branch", "filter-repo", "blame", "--version", "--help"}
ENV_DUMP_BUILTINS = {"printenv", "export", "declare", "typeset", "set", "env", "compgen"}
# $AWS_SECRET_ACCESS_KEY, ${GITHUB_TOKEN}, $DB_PASSWORD ... printed by these programs.
SECRET_VAR = re.compile(r"\$\{?(?!(?-i:(?:OLD)?PWD)\b)[a-z0-9_]*(secret|token|passw|pwd|api_?key|private_?key|credential|"
                        r"auth|session|cookie|dsn|database_url|conn)[a-z0-9_]*", re.I)
PRINTERS = {"echo", "printf", "print", "cat", "tee", "printenv", "env", "logger", "say", "pbcopy", "xargs"}
# Programs whose target (production, branch, remote) must be literal, not a $variable or $(...).
LITERAL_ARGS_ONLY = {"aws", "psql", "pgcli", "terraform", "pg_dump", "pg_dumpall", "pg_restore", "goose",
                     "migrate", "atlas", "dbmate", "kubectl", "helm"}
GLOB_SECRET_PROBES = [".env", ".env.local", ".env.production", ".netrc", ".pgpass", ".git-credentials"]
READERS = {"cat", "head", "tail", "less", "more", "grep", "egrep", "fgrep", "rg", "ag", "awk", "sed", "strings",
           "xxd", "od", "base64", "cut", "sort", "uniq", "nl", "bat", "jq", "yq", "diff", "cp", "tar", "zip"}


# =====================================================================================
# git / gh / aws
# =====================================================================================
def git_parts(argv):
    """Split a git argv into (global option pairs, subcommand, args)."""
    i, opts = 1, []
    while i < len(argv) and argv[i].startswith("-"):
        a = argv[i]
        if a in GIT_OPT_WITH_VALUE and i + 1 < len(argv):
            opts.append((a, argv[i + 1]))
            i += 2
        else:
            opts.append((a.split("=", 1)[0], a.split("=", 1)[1] if "=" in a else ""))
            i += 1
    sub = argv[i].lower() if i < len(argv) else ""
    return opts, sub, argv[i + 1:]


def git_dir(cwd, opts):
    d = cwd or os.getcwd()
    for k, v in opts:
        if k == "-C":
            d = os.path.join(d, os.path.expanduser(v))
    return d


GIT_CALLS = {"n": 0}
GIT_CACHE = {}


def git_out(d, *args):
    # A hook timeout lets the command run, so git lookups are capped and cached.
    key = (d,) + args
    if key in GIT_CACHE:
        return GIT_CACHE[key]
    GIT_CALLS["n"] += 1
    if GIT_CALLS["n"] > 6:
        block("command too complex for the guard to check in time; split it into smaller commands.")
    GIT_CACHE[key] = _git_out(d, *args)
    return GIT_CACHE[key]


def _git_out(d, *args):
    left = GIT_DEADLINE - (time.monotonic() - START)
    if left <= 0:
        block("git took too long to answer the guard's checks; split the command or check the repo config.")
    try:
        r = subprocess.run(["git", "-C", d] + list(args), capture_output=True, text=True, timeout=left)
        return r.returncode, r.stdout.strip()
    except subprocess.TimeoutExpired:
        block("git took too long to answer the guard's checks; split the command or check the repo config.")
    except Exception:
        return 1, ""


def check_git(argv, cwd):
    opts, sub, args = git_parts(argv)
    if sub in ("push", "config", "tag", "remote") or any(k == "-c" for k, _ in opts):
        for a in argv[1:]:
            if has_expansion(a):
                block("git %s with a $variable or $(...) (%s) is not allowed; use literal values "
                      "so the guard can check them." % (sub, a))
    for k, v in opts:
        if k == "-c" and GIT_DANGEROUS_CONFIG.match(v.split("=", 1)[0]):
            block("git -c %s is not allowed (it can change push, alias or hook behaviour)." % v.split("=", 1)[0])
    if sub and sub not in GIT_BUILTINS:
        rc, out = git_out(git_dir(cwd, opts), "config", "--get", "alias." + sub)
        if rc == 0 and out:
            block("git aliases (git %s = %s) are not allowed; run the full git command." % (sub, out))
    low = [a.lower() for a in args]

    # Secret files read from git objects (git show HEAD:.env, git cat-file ...).
    for a in args:
        for piece in re.split(r"[:=]", a):
            if piece and secret_path(piece, for_bash=True):
                block("access to a secret file through git (%s) is not allowed." % a)

    if sub == "config":
        reading = {"--get", "--get-all", "--get-regexp", "--list", "-l", "--show-origin", "get", "list"}
        if not reading & set(low):
            for a in args:
                if GIT_DANGEROUS_CONFIG.match(a.split("=", 1)[0]):
                    block("git config %s is not allowed (it can change push, alias or hook behaviour)." % a)

    if sub == "tag":
        listing = any(a in ("-l", "--list", "-v", "--verify", "--contains", "--no-contains", "--merged",
                            "--no-merged", "--points-at", "--column", "--no-column") or
                      re.match(r"^(-n\d*|--sort=|--format=|--contains=|--points-at=|--merged=)", a) for a in low)
        creating = any(a in ("-a", "-s", "-u", "-f", "-d", "-m", "-F", "--annotate", "--sign", "--force",
                             "--delete", "--message", "--file", "--local-user") or
                       re.match(r"^-[a-z]*[asufdm][a-z]*$", a) or a.startswith(("--message=", "--file="))
                       for a in low)
        positional = [a for a in args if not a.startswith("-")]
        if creating or (positional and not listing):
            block("creating or deleting tags is not allowed; humans create releases.")

    if sub == "push":
        positional = []
        skip_value = False
        for a in args:
            al = a.lower()
            if skip_value:
                skip_value = False
                continue
            if al in ("-o", "--push-option", "--receive-pack", "--exec", "--signed"):
                skip_value = al not in ("--signed",)
                continue
            if al in ("--force", "--force-with-lease", "--force-if-includes", "--mirror", "--delete",
                      "--prune", "--all", "--branches", "--tags", "--follow-tags") or \
                    al.startswith(("--force-with-lease=", "--force=", "--repo=")) or \
                    re.match(r"^-[a-z]*[fd][a-z]*$", al):
                block("git push %s is not allowed (force, delete, mirror, prune, all or tags)." % a)
            if a.startswith("-"):
                continue
            positional.append(a)
        refspecs = positional[1:]
        branch = None
        for r in refspecs:
            if r.startswith("+") or r.startswith(":"):
                block("force or delete refspec (%s) is not allowed." % r)
            dest = r.split(":")[-1].lower()
            if dest in ("head", "@"):
                if branch is None:
                    branch = git_out(git_dir(cwd, opts), "symbolic-ref", "--short", "-q", "HEAD")[1].lower()
                dest = branch or "unknown"
            dest = dest[len("refs/heads/"):] if dest.startswith("refs/heads/") else dest
            if dest in ("main", "master", "unknown"):
                block("pushing to main/master (or an unknown branch) is not allowed; open a PR.")
            if dest.startswith("refs/tags/") or re.match(r"^v?\d+\.\d+", dest) or "*" in r:
                block("pushing tags or wildcard refspecs (%s) is not allowed; humans create releases." % r)
        if not refspecs:
            branch = git_out(git_dir(cwd, opts), "symbolic-ref", "--short", "-q", "HEAD")[1].lower()
            if branch in ("main", "master", ""):
                block("pushing from main/master (or when the branch cannot be found) is not allowed. "
                      "Use: git push -u origin <feature-branch>.")
    return sub


GH_OUTWARD = [
    (["pr", "comment"]), (["pr", "review"]), (["pr", "close"]), (["pr", "edit"]), (["pr", "ready"]),
    (["pr", "reopen"]), (["issue"]), (["repo", "create"]), (["repo", "delete"]), (["repo", "edit"]),
    (["repo", "fork"]), (["repo", "archive"]), (["repo", "rename"]), (["gist"]), (["discussion"]),
    (["label"]), (["project"]), (["ruleset"]), (["cache", "delete"]), (["run", "cancel"]), (["run", "rerun"]),
]


def check_gh(argv):
    """Returns an 'ask' reason, '' or 'workflow-run'. Blocks on forbidden actions."""
    a = [x.lower() for x in argv[1:]]
    if a[:2] == ["pr", "merge"]:
        block("merging PRs is not allowed; humans merge.")
    if a[:1] == ["alias"] and len(a) > 1 and a[1] in ("set", "import"):
        block("creating gh aliases is not allowed.")
    if a[:1] == ["release"] and len(a) > 1 and a[1] in ("create", "delete", "edit", "upload"):
        block("creating or changing releases is not allowed.")
    if a[:1] in (["secret"], ["variable"]):
        block("managing GitHub secrets and variables is not allowed.")
    if a[:2] == ["auth", "token"] or (a[:2] == ["auth", "status"] and "--show-token" in a) or \
            ("-t" in a and a[:2] == ["auth", "status"]):
        block("printing the GitHub token is not allowed.")
    if a[:1] == ["api"]:
        if any(has_expansion(x) for x in a):
            block("gh api with a $variable or $(...) is not allowed; use literal values.")
        method = "get"
        for i, x in enumerate(a):
            if x in ("-x", "--method") and i + 1 < len(a):
                method = a[i + 1]
            elif x.startswith("--method="):
                method = x.split("=", 1)[1]
            elif x.startswith("-x") and len(x) > 2:
                method = x[2:]
            elif re.match(r"^-[a-z]*f", x) or x in ("--field", "--raw-field", "--input") or \
                    x.startswith(("--field", "--raw-field", "--input")):
                method = "post" if method == "get" else method
        if method != "get":
            block("gh api writes (POST/PUT/PATCH/DELETE or -f fields) are not allowed; ask the user.")
    if a[:2] == ["workflow", "run"]:
        return "workflow-run"
    for prefix in GH_OUTWARD:
        if a[:len(prefix)] == prefix and not (len(a) > len(prefix) and a[len(prefix)] in ("list", "view", "status")):
            return "'gh %s' posts or changes something on GitHub that others see." % " ".join(a[:2])
    return ""


# `git push` is listed in sandbox.excludedCommands (.claude/settings.json): it runs OUTSIDE the sandbox
# with the user's full access, so for it this guard is the only check. Keep both in sync.
# How Claude Code 2.1.267 decides (read from its code, confirmed in a live trial): it splits the
# command into parts; for each part it drops VAR=value prefixes, wrappers (timeout, nohup, command,
# noglob, ...) and quotes/backslashes in the first word; if ANY part then matches, the WHOLE command
# string runs unsandboxed (the Monitor tool uses the same check).
# Git accepts option bundles (-uo), abbreviations (--pu, --mirr) and the shell expands globs, so
# parsing options with a block list does not work (review rounds 6-7). Instead exactly ONE form is
# allowed, character by character. Anything else that mentions git push is blocked.
UNSANDBOXED_HINT = re.compile(r"\bgit\s+push\b", re.I)
PUSH_BRANCH = r"(?:feat|fix|chore)/[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)*"
PUSH_FORM = re.compile(r"git push(?: -u| --set-upstream)? origin (" + PUSH_BRANCH + r")")
PUSH_HELP = ("git push runs outside the sandbox, so only this exact form is allowed, as its own Bash "
             "call, run from the project root: git push -u origin <feat|fix|chore>/<name> "
             "(lower-case letters, digits, . _ - and /). Anything else: ask the user to push.")


def push_form(cmd):
    m = PUSH_FORM.fullmatch(cmd.strip())
    return m.group(1) if m and ".." not in m.group(1) and not m.group(1).endswith((".", ".lock", "/")) else None


def check_plain_unsandboxed(cmd):
    if UNSANDBOXED_HINT.search(re.sub(r"[\"'\\]", "", cmd)) and not push_form(cmd):
        block(PUSH_HELP)


def check_push_repo(cwd, branch):
    """The unsandboxed push must use the project's own .git (config and hooks the sandbox protects) from
    the project root, push to GitHub over HTTPS, use no custom hooks folder, and push a branch."""
    env_root = os.environ.get("CLAUDE_PROJECT_DIR") or ""
    root = os.path.realpath(env_root)
    if not env_root or os.path.realpath(cwd).lower() != root.lower():
        block("git push may only run from the project root (cd %s first, in its own Bash call)." % env_root)
    rc, out = git_out(cwd, "rev-parse", "--absolute-git-dir", "--show-toplevel")
    lines = out.splitlines()
    if not (rc == 0 and len(lines) == 2 and
            os.path.realpath(lines[0]).lower() == (root + "/.git").lower() and
            os.path.realpath(lines[1]).lower() == root.lower()):
        block("git push may only run in this project's own repository (a .git folder at the project "
              "root, not a worktree or nested repo). Ask the user to push.")
    rc, url = git_out(cwd, "remote", "get-url", "--push", "origin")
    if rc != 0 or not re.match(r"^https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+?(\.git)?$", url):
        block("git push only goes to an https://github.com/<org>/<repo> origin (found: %s). "
              "Ask the user to push." % (url or "none"))
    rc, hooks = git_out(cwd, "config", "--get", "core.hooksPath")
    if hooks:
        block("git push is not allowed while core.hooksPath is set (%s): those hooks would run outside "
              "the sandbox. Ask the user to push." % hooks)
    rc, refs = git_out(cwd, "for-each-ref", "--format=%(refname)", "refs/heads/" + branch, "refs/tags/" + branch)
    if refs.split() != ["refs/heads/" + branch]:
        block("git push %s: it must be an existing local branch and not also a tag." % branch)


def check_unsandboxed(raw_argv, argv, cwd):
    """Extra rules for `git push`, which skips the sandbox. check_plain_unsandboxed already allowed
    only the exact form; this re-checks the parsed words and the repository."""
    if prog(argv) != "git" or len(argv) < 2 or argv[1] != "push":
        return
    branch = push_form(" ".join(raw_argv))
    if raw_argv != argv or not branch:
        block(PUSH_HELP)
    check_push_repo(cwd or os.getcwd(), branch)


AWS_OPT_WITH_VALUE = {"--profile", "--region", "--output", "--endpoint-url", "--query", "--cli-read-timeout",
                      "--cli-connect-timeout", "--color", "--ca-bundle", "--cli-binary-format"}


def aws_service_op(argv):
    pos, i = [], 1
    while i < len(argv) and len(pos) < 2:
        a = argv[i]
        if a.startswith("--"):
            i += 2 if a in AWS_OPT_WITH_VALUE else 1
            continue
        pos.append(a.lower())
        i += 1
    return (pos + ["", ""])[:2]


def check_prod_aws(argv):
    service, op = aws_service_op(argv)
    if service in ("secretsmanager", "ssm", "kms") or (service == "sts" and op == "assume-role"):
        block("reading production secrets or assuming production roles is not allowed.")
    if service == "s3" and op in ("cp", "sync", "mv", "rm", "rb", "mb", "presign"):
        block("copying or changing production S3 data is not allowed.")
    if service == "s3api" and op.startswith(("get-object", "put-", "delete-", "copy-")):
        block("reading or changing production S3 objects is not allowed.")
    read_only = op.startswith(("describe-", "list-")) or \
        (op.startswith("get-") and not op.startswith(("get-secret", "get-parameter", "get-object"))) or \
        (service == "s3" and op == "ls") or (service == "logs" and op in ("tail", "filter-log-events"))
    if not read_only:
        block("only read-only AWS commands (describe/list/get, s3 ls, logs) are allowed against production.")


PROD = re.compile(r"(?<![a-z0-9])prod(uction)?(?![a-z0-9])")


# =====================================================================================
# Bash
# =====================================================================================
def strip_commit_messages(tokens):
    """Commit messages are text, not commands: drop them before the rough text checks."""
    out, skip = [], False
    for i, t in enumerate(tokens):
        if skip:
            skip = False
            continue
        if t in ("-m", "--message") and "commit" in tokens[:i] and "git" in tokens[:i]:
            skip = True
            continue
        if t.startswith("--message=") and "git" in tokens[:i]:
            continue
        out.append(t)
    return out


def check_bash(cmd, cwd, depth=0):
    """Returns an 'ask' reason or ''. Raises Blocked."""
    if depth > 3:
        block("too many nested shells (bash -c / eval) to check.")
    if len(cmd.encode("utf-8", "replace")) > MAX_COMMAND_BYTES:
        block("command is too long for the guard to check in time; split it or put it in a script file.")
    if depth == 0:
        check_plain_unsandboxed(cmd)
    tokens = tokenize(cmd)
    if sum(1 for _ in segments(tokens)) > MAX_SEGMENTS:
        block("command has too many parts for the guard to check in time; split it into smaller commands.")
    scan =" ".join(strip_commit_messages(tokens)) if "commit" in tokens else cmd
    for pattern, reason in TEXT_RULES:
        if re.search(pattern, scan, re.I):
            block(reason)

    ask_reason = ""
    for t in strip_commit_messages(tokens):
        for piece in re.split(r"[:=]", t):
            if piece and secret_path(piece, for_bash=True):
                block("access to a secret or credential file (%s) is not allowed." % t)
        base = t.rstrip("/").split("/")[-1]
        # Shell wildcards only match dotfiles when the pattern itself starts with "." or "[".
        if any(ch in t for ch in "*?[") and base[:1] in (".", "[") and \
                any(fnmatch.fnmatch(p, base) for p in GLOB_SECRET_PROBES):
            block("a wildcard that can match a secret file (%s) is not allowed." % t)

    # A branch change and a push in one command: the guard cannot know which branch is pushed.
    git_subs = []
    for seg in segments(tokens):
        a = unwrap([t for t in seg if t not in REDIRECTS])
        if prog(a) == "git":
            _, sub, rest = git_parts(a)
            if sub == "push":
                pos = [x for x in rest if not x.startswith("-")]
                implicit = len(pos) < 2 or any(x.split(":")[-1].lower().lstrip("+") in ("head", "@") for x in pos[1:])
                sub = "push-implicit" if implicit else "push"
            elif sub == "branch" and not any(re.match(r"^-[A-Za-z]*[mM]", x) or
                                             (x.startswith("--") and len(x) >= 4 and "--move".startswith(x.split("=")[0]))
                                             for x in rest):
                sub = "branch-no-switch"     # listing or creating branches does not change the current one
            git_subs.append(sub)
    if "push-implicit" in git_subs and any(s in BRANCH_CHANGE_GIT
                                           for s in git_subs[:git_subs.index("push-implicit")]):
        block("changing branch and then pushing without naming the branch is not allowed; "
              "name it: git push -u origin <feature-branch>.")
    if any(prog(unwrap([t for t in seg])) in ("which", "command", "type", "whereis") for seg in segments(tokens)) \
            and "$" in tokens:
        block("running a program found with $(which ...) is not allowed; call it by name.")

    is_prod_cmd = bool(PROD.search(cmd.lower())) or "/envs/prod" in cwd.lower()
    def real_protected_dir(d):
        try:
            return under_claude(os.path.realpath(d) + "/") or under_claude(d + "/")
        except Exception:
            return True
    cur_dir = cwd or os.getcwd()
    in_protected_dir = real_protected_dir(cur_dir) if cwd else False   # also true after "cd .claude" below

    def resolves_protected(x):
        """Does a literal path (resolved from the current directory, following symlinks) hit a guard rail?"""
        if not x or x.startswith("-") or has_expansion(x):
            return False
        return guard_rail_path(x, cur_dir) or under_claude(
            os.path.realpath(os.path.join(cur_dir, os.path.expanduser(x))) + "/")
    for seg in segments(tokens):
        is_prod = is_prod_cmd
        seg_mentions = any(mentions_protected(t) for t in seg)
        redirect_targets = [seg[i + 1] for i, t in enumerate(seg) if t in WRITE_REDIRECTS and i + 1 < len(seg)]
        argv = [t for i, t in enumerate(seg)
                if t not in REDIRECTS and not (i > 0 and seg[i - 1] in REDIRECTS)
                and not re.fullmatch(r"\d", t)]
        raw_argv = argv
        argv = unwrap(argv)
        p = prog(argv)
        writes, unknown_target = False, False
        if redirect_targets:
            if any(mentions_protected(x) or resolves_protected(x) for x in redirect_targets) or \
                    (in_protected_dir and any(not x.startswith("/") and x not in ("1", "2") for x in redirect_targets)):
                block("the agent may not change protected files (.claude/, .git/config, .git/hooks/, .mcp.json) "
                      "from the shell.")
        if not p:
            continue
        args = [a.lower() for a in argv[1:]]
        check_unsandboxed(raw_argv, argv, cur_dir)

        # Directory changes inside the command.
        if p in ("cd", "pushd"):
            if any(has_expansion(a) for a in argv[1:]):
                in_protected_dir = True          # unknown directory: assume the worst
            elif any(mentions_protected(a) for a in argv[1:]):
                in_protected_dir = True
            else:
                target = next((a for a in argv[1:] if not a.startswith("-")), "~")
                cur_dir = os.path.join(cur_dir, os.path.expanduser(target))
                if real_protected_dir(cur_dir):
                    in_protected_dir = True
            continue

        # Nested shells: check the inner command too (bash -c '...', eval '...').
        if p == "eval":
            r = check_bash(" ".join(argv[1:]), cwd, depth + 1)
            ask_reason = ask_reason or r
        if p in SHELLS:
            for i, a in enumerate(argv[1:-1], start=1):
                if re.match(r"^-[a-z]*c[a-z]*$", a):
                    r = check_bash(argv[i + 1], cwd, depth + 1)
                    ask_reason = ask_reason or r

        # Environment dumps.
        if p in ENV_DUMP_BUILTINS:
            positional = [a for a in argv[1:] if not a.startswith("-")]
            if p in ("printenv", "env"):
                block("dumping environment variables is not allowed (they may hold secrets).")
            if p in ("declare", "typeset", "export", "local", "readonly") and \
                    any(re.match(r"^-[a-z]*p", a) for a in args):
                block("printing variables with -p is not allowed (they may hold secrets).")
            # -F lists function names only (-f would print function bodies, which may hold tokens).
            functions_only = p in ("declare", "typeset") and argv[1:] and all(a == "-F" for a in argv[1:])
            if p in ("export", "declare", "typeset") and not positional and not functions_only:
                block("dumping environment variables is not allowed (they may hold secrets).")
            if p == "set" and not argv[1:]:
                block("dumping environment variables is not allowed (they may hold secrets).")
            if p == "compgen" and "-e" in args:
                block("dumping environment variables is not allowed (they may hold secrets).")
        if p == "ps" and ((args and not args[0].startswith("-") and "e" in args[0]) or "-E" in argv[1:]):
            block("showing process environments is not allowed (they may hold secrets).")
        if p in PRINTERS and any(SECRET_VAR.search(a) for a in argv[1:]):
            block("printing secret environment variables is not allowed.")

        # Reading .env through recursive search.
        if p in ("grep", "egrep", "fgrep") and any(re.match(r"^-[a-z]*[rR][a-z]*$", a) or a in ("--recursive",
                                                   "--dereference-recursive") for a in argv[1:]):
            block("grep -r also reads secret files such as .env. Use the Grep tool or rg, which skip "
                  "gitignored files.")
        if p == "rg" and any(a in ("--hidden", "--no-ignore", "-u", "-uu", "-uuu", "--no-ignore-vcs", "-.")
                             for a in args):
            block("rg --hidden/--no-ignore also reads secret files such as .env.")
        if p == "find":
            for i, a in enumerate(args[:-1]):
                if a in ("-name", "-iname", "-path", "-ipath", "-regex", "-iregex"):
                    pat = argv[1:][i + 1]
                    if any(fnmatch.fnmatch(x, pat.split("/")[-1]) for x in GLOB_SECRET_PROBES) and \
                            any(x in args for x in ("-exec", "-execdir", "-ok", "-print0")) or \
                            (a.endswith("regex") and "env" in pat.lower()):
                        block("find with a pattern that matches secret files (%s) is not allowed." % pat)

        # Writes.
        if p == "git":
            sub = check_git(argv, cwd)
            if sub in GIT_TREE_WRITE:
                writes = True
                unknown_target = sub in UNKNOWN_TARGET_GIT and not any(x in args for x in ("--check", "--stat",
                                                                                            "list", "show"))
        elif INTERPRETER.match(p):
            is_test = len(argv) == 2 and os.path.normpath(argv[1]).lower() == ".claude/hooks/test_guard.py" \
                and p.startswith("python")
            if not is_test:
                writes = True
                if p in SHELLS and len(argv) > 1 and not argv[1].startswith("-"):
                    unknown_target = True            # running a script file: its contents are unknown
        elif p in WRITE_PROGS:
            writes = True
        elif p in ("sed", "gsed") and any(a.startswith("-i") or a.startswith("--in-place") for a in args):
            writes = True
        elif p == "find" and any(a in ("-delete", "-exec", "-execdir", "-ok", "-okdir") for a in args):
            writes = True
        elif p == "awk" and "inplace" in args:
            writes = True
        if p in WRITE_PROGS | {"sed", "find", "awk"} and any(a in SUBST_MARKS or a.endswith("$")
                                                             for a in raw_argv):
            unknown_target = True
        # Interpreters reading the environment (python -c, node -e, awk ENVIRON, jq env ...).
        if (INTERPRETER.match(p) or p in ("awk", "gawk", "jq", "yq")) and \
                any(ENV_READ.search(a) for a in argv[1:]):
            block("reading environment variables from interpreter one-liners is not allowed (they may hold secrets).")
        if writes and (seg_mentions or in_protected_dir or (unknown_target and p == "git") or
                       any(resolves_protected(a) for a in argv[1:])):
            block("the agent may not change protected files (.claude/, .git/config, .git/hooks/, .mcp.json) "
                  "from the shell. Rules, skills and agents are changed with the Edit/Write tools; hooks and "
                  "settings only by humans.")
        if writes and unknown_target and p != "git" and any(a in SUBST_MARKS or a.endswith("$") for a in raw_argv):
            block("file-changing commands with $(...) or `...` targets are not allowed; use literal paths.")

        # Production, branch and remote targets must be literal.
        if p in LITERAL_ARGS_ONLY and any(has_expansion(a) for a in argv[1:]):
            is_prod = True       # unknown target: apply the production rules

        if p == "gh":
            r = check_gh(argv)
            if r == "workflow-run":
                if is_prod:
                    block("triggering production workflows is not allowed.")
            elif r:
                ask_reason = ask_reason or r
        if p == "terraform" and ("destroy" in args or "-destroy" in args):
            block("terraform destroy is not allowed; ask the user.")

        if is_prod:
            if p == "terraform" and any(a in ("apply", "import", "taint", "untaint") for a in args):
                block("changing production infrastructure is not allowed.")
            if p == "terraform" and "state" in args and any(a in ("rm", "mv", "push", "replace-provider")
                                                            for a in args):
                block("changing production infrastructure is not allowed.")
            if p in ("pg_dump", "pg_dumpall", "pg_restore", "goose", "migrate", "atlas", "dbmate"):
                block("migrating, dumping or restoring production databases is not allowed.")
            if p in ("psql", "pgcli"):
                joined = " ".join(args)
                if not re.search(r"replica|read-?only|(?<![a-z0-9])ro(?![a-z0-9])|[_-]ro\b", joined):
                    block("production database access must use the read replica / read-only role.")
                if "<" in seg or any(a in ("-f", "--file") or a.startswith("--file=") for a in args):
                    block("running SQL files against production is not allowed; paste read-only queries.")
                if re.search(r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|copy|merge|call|"
                             r"do|vacuum|reindex|cluster|lock)\b", joined):
                    block("write SQL against production is not allowed.")
            if p == "aws":
                check_prod_aws(argv)
            if p in ("kubectl", "helm") and not (args[:1] and args[0] in ("get", "describe", "logs", "list",
                                                                          "status", "version", "top")):
                block("only read-only kubectl/helm commands are allowed against production.")
    return ask_reason


# =====================================================================================
# MCP and web
# =====================================================================================
# An MCP tool runs without asking only if its first word is a read verb and no other word in
# its name is a write or sensitive word. Everything else asks the user (allowlist, not blocklist).
MCP_READ_VERBS = {"get", "list", "read", "search", "find", "describe", "view", "show", "lookup", "count"}
MCP_WRITE_WORDS = {"send", "post", "reply", "forward", "draft", "publish", "share", "invite", "create",
                   "update", "upsert", "delete", "remove", "upload", "write", "push", "merge", "exec", "run",
                   "execute", "batch", "set", "put", "patch", "insert", "move", "copy", "assign", "close",
                   "approve", "transfer", "pay", "charge", "book", "cancel", "edit", "add", "submit",
                   "navigate", "click", "type", "fill", "press", "eval", "sql", "query", "invoke", "call",
                   "trigger", "deploy", "save", "modify", "change", "replace", "reset", "archive", "respond",
                   "notify", "secret", "token", "password", "credential", "key", "fetch", "download", "url",
                   "webhook", "and", "or", "then"}


def mcp_is_read_only(action):
    words = [w.lower() for w in re.split(r"[_\-.\s]+|(?<=[a-z])(?=[A-Z])", action) if w]
    if not words or words[0] not in MCP_READ_VERBS:
        return False
    return not any(w in MCP_WRITE_WORDS or w.rstrip("s") in MCP_WRITE_WORDS for w in words[1:])


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        block("could not read the tool request.")
    if not isinstance(data, dict):
        block("unexpected tool request format.")
    tool = data.get("tool_name", "")
    ti = data.get("tool_input", {})
    if ti is None:
        ti = {}
    if not isinstance(tool, str) or not isinstance(ti, dict):
        block("unexpected tool request format.")
    cwd = str(data.get("cwd") or "")

    for key in ("file_path", "notebook_path", "path"):
        p = ti.get(key)
        if p is None:
            continue
        if not isinstance(p, str):
            block("unexpected tool request format.")
        if secret_path(p):
            block("access to a secret or credential file (%s) is not allowed." % p)
        if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit") and guard_rail_path(p, cwd):
            block("the agent may not change its own guard rails (.claude/settings*, .claude/hooks/, "
                  ".git/config, .git/hooks/, .mcp.json).")
    if tool == "Grep":
        # Grep can print file contents. Block patterns aimed at dotfile secrets (".en*", ".env").
        g = ti.get("glob")
        if g is not None and not isinstance(g, str):
            block("unexpected tool request format.")
        if g:
            base = g.rstrip("/").split("/")[-1]
            if secret_path(g) or (base[:1] in (".", "[") and any(fnmatch.fnmatch(x, base) for x in GLOB_SECRET_PROBES)):
                block("a file pattern that can match secret files (%s) is not allowed." % g)

    if tool == "PowerShell":
        block("the PowerShell tool is not used in this project; use Bash.")
    if tool == "Monitor" and ti.get("ws") is not None:
        # The WebSocket is opened by Claude Code itself, outside the sandbox and its network allowlist.
        ws = ti.get("ws")
        url = ws.get("url") if isinstance(ws, dict) else None
        if not isinstance(url, str) or ti.get("command") is not None:
            block("unexpected tool request format.")
        ask("Monitor wants to open a WebSocket to %s outside the sandbox. Approve only if you know this "
            "service and nothing private is sent." % url)
    if tool in ("Bash", "Monitor"):
        # Monitor runs its command through the same sandbox decision as Bash (excludedCommands included).
        cmd = ti.get("command")
        if not isinstance(cmd, str):
            block("unexpected tool request format.")
        r = check_bash(cmd, cwd)
        if r:
            ask(r + " Approve only if you agreed the exact text and audience.")
    elif tool == "WebFetch":
        url = ti.get("url")
        if not isinstance(url, str):
            block("unexpected tool request format.")
        if "?" in url or "#" in url:
            ask("this web request carries data in its URL (%s). Approve only if nothing private is in it." % url)
    if tool.startswith("mcp__"):
        # Any string in the arguments that names a secret file (paths: [...], files: [...]).
        def strings(v, depth=0):
            if depth > 5:
                return
            if isinstance(v, str):
                yield v
            elif isinstance(v, dict):
                for x in v.values():
                    for s in strings(x, depth + 1):
                        yield s
            elif isinstance(v, list):
                for x in v:
                    for s in strings(x, depth + 1):
                        yield s
        for s in strings(ti):
            if len(s) < 1024 and "\n" not in s and secret_path(s):
                block("an MCP tool argument names a secret or credential file (%s)." % s)
    if tool in ("Bash", "Monitor", "WebFetch"):
        pass
    elif tool.startswith("mcp__"):
        if tool not in MCP_ALLOW:
            action = tool.rsplit("__", 1)[-1]
            if not mcp_is_read_only(action):
                ask("'%s' is not on the read-only list and may send or change something outside this "
                    "computer. Approve only if you agreed the exact recipients, text and attachments." % tool)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Blocked as b:
        print("BLOCKED by guard (%s): %s If this is really needed, stop and ask the user to do it themselves."
              % (POLICY, b), file=sys.stderr)
        sys.exit(2)
    except SystemExit:
        raise
    except BaseException as e:  # fail closed on any bug in this file
        print("BLOCKED by guard (%s): internal guard error (%s: %s). "
              "Ask the user to run: python3 .claude/hooks/test_guard.py" % (POLICY, type(e).__name__, e),
              file=sys.stderr)
        sys.exit(2)
