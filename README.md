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

    python -m demo1

This runs the script with some not-terribly-well-thought-out default settings.
For a list of these settings, type:

    python -m demo1 --help

There are no input files or config files to speak of at this point in time.

The output currently leaves something to be desired.  It is currently just
JSON output listing the events which occured in the simulation, intended
to be written to a file for use as input to something else.
(for instance, the animation script accepts it as input)

# Dependencies

Python (2 or 3) should be able to run the core script with no additional
dependencies.

Side scripts such as `animation.py` may have a large number of additional
dependencies and I don't plan to keep tabs on all of them here. Ask for
help if you want to run one of them.

