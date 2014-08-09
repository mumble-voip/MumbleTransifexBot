Requires pygithub, plumbum

Meant to be run regularily as part of a root cronjob. Pulls updated
translations from transifex and if anything relevant changed creates
a pull request with the translation update to the mumble master repository.