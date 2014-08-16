#!/usr/bin/env python
# -*- coding: utf-8

# Copyright (C) 2014 Stefan Hacker <dd0t@users.sourceforge.net>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:

# - Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
# - Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
# - Neither the name of the Mumble Developers nor the names of its
#   contributors may be used to endorse or promote products derived from this
#   software without specific prior written permission.

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# `AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE FOUNDATION OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""
Meant to be run regularily as part of a root cronjob. Pulls updated translations from
transifex and if anything relevant changed creates a pull request with the translation
update to the mumble master repository.
"""

import ConfigParser
from argparse import ArgumentParser
from logging import basicConfig, getLogger, DEBUG, INFO, WARNING, ERROR, debug, error, info, warning, exception
from github import Github
from plumbum.cmd import git, tx
from plumbum import ProcessExecutionError, local
import sys
import os
import re

def getExistingPullRequest(g, user, repo):
    s = g.search_issues("type:pr is:open repo:%(repo)s author:%(user)s" % {'user': user,
                                                                    'repo': repo})
    pullrequests = s.get_page(0)
    total = len(pullrequests)
    if total == 0:
        # We have to create a PR
        debug("No open pull request found for %s in %s", user, repo)
        return None
    elif total == 1:
        # We can reuse the existing PR
        pr = pullrequests[0]
        debug("Reusing existing PR %d from %s", pr.number, pr.created_at)
        return pr
    else:
        # More then one PR pending. That's not right. Abort
        raise Exception("Have %d PRs pending. This is unexpected." % total)

def createNewPullRequest(g,
                         target_owner, target_repo, target_branch,
                         base_owner, base_branch,
                         request_title, request_body):
    
    u = g.get_user(target_owner)
    r = u.get_repo(target_repo)
    pr = r.create_pull(title = request_title,
                  body = request_body,
                  head = base_owner + ":" + base_branch,
                  base = target_branch)
    return pr

if __name__ == "__main__":
    parent_parser = ArgumentParser(
        description = 'Create pull requests to mumble from transifex translation updates',
        epilog = __doc__)
    
    parent_parser.add_argument('-c', '--config', help = 'Configuration file (default: %(default)s)', default = '/etc/prfromtransifex.ini')
    parent_parser.add_argument('--setup', help = "If set sets up needed git clone and then exits", action='store_true')
    parent_parser.add_argument('-v', '--verbose', help = 'Verbose logging', action='store_true')

    args = parent_parser.parse_args()    
    basicConfig(level = (DEBUG if args.verbose else INFO),
                format='%(asctime)s %(levelname)s %(message)s')
    
    debug("Loading configuration from: %s", args.config)

    cfg = ConfigParser.RawConfigParser()
    cfg.read(args.config)
    
    user = cfg.get('github', 'user')
    password = cfg.get('github', 'password')
    email = cfg.get('github', 'email')
    
    mode = cfg.get('transifex', 'mode')
    minpercent = cfg.get('transifex', 'minpercent')
    
    wr_owner = cfg.get('workingrepo', 'owner')
    wr_repo = cfg.get('workingrepo', 'repo')
    wr_branch = cfg.get('workingrepo', 'branch')
    wr_url = cfg.get('workingrepo', 'url')
    wr_path = cfg.get('workingrepo', 'path')
    
    tr_owner = cfg.get('targetrepo', 'owner')
    tr_repo = cfg.get('targetrepo', 'repo')
    tr_branch = cfg.get('targetrepo', 'branch')
    tr_url = cfg.get('targetrepo', 'url')
    
    pr_title = cfg.get('pullrequest', 'title')
    pr_body = cfg.get('pullrequest', 'body')
    pr_commit = cfg.get('pullrequest', 'commit')
    
    prifile = cfg.get('misc', 'prifile')
    pritemplate = cfg.get('misc', 'pritemplate')
    qrcfile = cfg.get('misc', 'qrcfile')
    qrctemplate = cfg.get('misc', 'qrctemplate')
    additionaltsfiles = cfg.get('misc', 'additionaltsfiles')
    
    if args.setup or not os.path.exists(wr_path):
        info("Setting up git repo")
        debug(git["clone", wr_url, wr_path]())
        with local.cwd(wr_path):
            debug(git["config", "user.name", user]())
            debug(git["config", "user.email", email]())
            debug(git["remote", "add", "target", tr_url]())
            
        info("Done")
        
        if args.setup:
            sys.exit(0)
        
    info("Checking for pending PR")
    g = Github(user, password)
    pr = getExistingPullRequest(g,
                                user = user,
                                repo = tr_owner + "/" + tr_repo)
    if pr:
        info("Already have pending PR %d", pr.number)
        # As long as we have a pending PR we want to make sure we
        # keep working on that basis so potential review inside of
        # of the PR isn't disturbed. Changes should be added on as
        # additional commits on top of the existing PR.
        remote = "origin"
        branch = wr_branch
    else:
        info("No pending PR, will be creating a new one")
        # When we have no pending requests we want to base our branch
        # on the most recent mumble version to make fast-forward application
        # of our patches as easy as possible.
        remote = "target"
        branch = tr_branch 

    with local.cwd(wr_path):
        info("Updating remote '%s'", remote)
        debug(git["fetch", remote]())
        info("Resetting to branch '%s'", branch)
        debug(git["reset", remote + "/" + branch, "--hard"]())
        info("Cleaning repository")
        debug(git["clean", "-f", "-x", "-d"]())
        
        info("Pulling translations")
        txout = tx["pull", "-f", "-a", "--mode=" + mode, "--minimum-perc=" + minpercent]()
        debug(txout)
        
        # Add all .ts files tx pull got to repo
        paths, files = zip(*re.findall(r"^\s->\s[\w_]+:\s([\w/\_]+/([\w_]+\.ts))$", txout, flags=re.MULTILINE))
        debug(git["add"](*paths))
        
        # Add additional ts files not in control of transifex (e.g. English source translation)
        files = list(files)
        files.extend(additionaltsfiles.split(" "))
        files.sort()
        
        # Write pri file listing ts files for build
        prifilepath = os.path.join(wr_path, prifile)
        info("Updating translations listing file '%s'", prifilepath)
        tsfiles = (" ".join(files))
        with open(prifilepath, "w") as f:
            f.write(pritemplate % {'files': tsfiles})
        debug(git["add"](prifilepath))
        
        # Write qrc file listing qm files built from ts files for build
        qrcfilepath = os.path.join(wr_path, qrcfile)
        info("Updating translations listing file '%s'", qrcfilepath)
        tstoqm = lambda f: " <file>%s</file>" % re.sub(r"(^.*)\.ts$", r"\1.qm", f)
        qmfiles = os.linesep.join([tstoqm(f) for f in files])
        with open(qrcfilepath, "w") as f:
            f.write(qrctemplate % {'files': qmfiles})
        debug(git["add"](qrcfilepath))

        # Check if the repo changed
        debug("Checking for modifications")
        changed, changedfiles, _ = git["diff", "--cached", "--name-only", "--exit-code"].run(retcode=(0,1))
        if not changed:
            info("No changes to translations, done")
            sys.exit(0)
        
        debug("Changed files: %s", " ".join(os.linesep.split(changedfiles)))
    
        info("Things changed & force pushing")
        debug(git["commit", "-m", pr_commit % {'mode': mode,
                            'minpercent': minpercent,
                            'langcount': len(files)}]())
        
        debug(git["push", "-f", "origin", wr_branch]())
    
    if not pr:
        info("No existing PR, creating new one")
        pr = createNewPullRequest(g,
                                  target_owner = tr_owner,
                                  target_repo = tr_repo,
                                  target_branch = tr_branch,
                                  base_owner = wr_owner,
                                  base_branch = wr_branch,
                                  request_title = pr_title,
                                  request_body = pr_body)
        
        info("Created PR %d", pr.number)

    
