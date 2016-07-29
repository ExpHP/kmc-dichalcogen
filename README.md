# kmc-dichalcogen

## Get it

**Option 1**: Using git:

    git clone https://github.com/ExpHP/kmc-dichalcogen.git

which will put it all in a folder called `kmc-dichalcogen`.
Updates can be received by doing `git pull` in that folder.

**Option 2**: You can [download a zip file here](https://github.com/ExpHP/kmc-dichalcogen/archive/master.zip).
(this link always points to the latest version)

## Run it

Go to where the "demo1" folder is located (don't go inside it) and run:

    python3 -m demo1 test-cfg.yaml

This runs the script with some not-terribly-well-thought-out default settings.
For a list of these settings, type:

    python3 -m demo1 --help

The config file specifies stuff like
which events are allowed to occur in the simulation,
and their rates or energy barriers.
It is a recent addition and its contents are not documented
(beyond that it is, obviously, a YAML file)
on the basis that they are likely to undergo significant change.

The output currently leaves something to be desired.  It is currently just
JSON output listing the events which occured in the simulation, intended
to be written to a file for use as input to something else.
(for instance, the animation script accepts it as input, and there will
eventually be a post-processing script that uses it to computes rates)

# Testing

A small number of components have unit tests:

    ./tests.sh

The program has a lot of redundant data structures to improve efficiency;
these can be checked for internal consistency using debug flags like
`--no-incremental` or `--validate-every`.

Some important higher-level properties like probability distribution
are difficult to fit into the standard testing model, and will require
a more scientific approach.

# Dependencies

Requires Python 3 now, mostly because I forgot that I was trying to
accomodate Python 2 (oopsies).

At the time of writing, the core script requires `numpy` and `tabulate`
(and the numpy dependence is only used for [one terrible feature][1]
that I want to eventually remove).  Other scripts may require whatever.

In case this text falls out of date (which it likely will), just try running
it and ask for help when it fails.

[1]: https://github.com/ExpHP/kmc-dichalcogen/blob/2631c1c372e9df55907b8cc0c8459229c79e7cbf/demo1/incremental.py#L64
