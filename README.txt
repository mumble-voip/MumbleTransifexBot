Requires pygithub, plumbum

Meant to be run regularily as part of a user cronjob. Pulls updated
translations from transifex and if anything relevant changed creates
a pull request with the translation update to the mumble master repository.

If there is already a pull request pending a new commit is added to
that request. This is meant to allow a review and fix before  merge
cycle on github as it is possible for normal pull requests.

