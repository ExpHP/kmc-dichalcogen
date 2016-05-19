# pykmc

## Get it

**Option 1**: The cool people way (using git):

    git clone https://github.com/ExpHP/kmc-dichalcogen.git

which will put it all in a folder called `kmc-dichalcogen`.

**Option 2**: You can download a zip file from this page. (Ctrl+F for "Clone or download")

## Run it

Go to where the "demo1" folder is located (don't go inside it)
and run: (The `-m` is *not optional*)

    python -m demo1

This runs the script with some not-so-well thought out default settings.
Speaking of settings, for a list of them, type:

    python -m demo1 --help

There are no input files or config files to speak of (yet).

The output is currently just JSON intended to be saved to a file and used
for other nefarious purposes (like analysis, or input to the animation
script).

# Dependencies

None to run the main script, which should be able to be run by both
python2 and python3 out of the box.

Side scripts such as `animation.py` will depend on whatever they gosh darn
well feel like depending on, and will probably require anything from numpy
to networkx, to python3.




