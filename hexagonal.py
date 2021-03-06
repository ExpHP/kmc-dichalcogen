
'''
Defines two three-index formats for working with honeycomb and hexagonal
graphs.

# TODO test unused bits

Cubic
=====
This format defines points as a linear combination of 3 vectors
``xy = a * avec + b * bvec + c * cvec``, where ``avec`` represents
edges pointing SE, ``bvec`` represents edges pointing NE, and ``cvec``
represents edges pointing W.

This format is particularly useful for relationships such as distance
and neighborship on a hexagonal graph, because the format reflects the
symmetry of the graph; this makes many of the formulas much simpler.

Axial
=====

For points on a hexagonal lattice, ``a+b+c`` is always 0, making one
of the coordinates in cubic coords seem redundant.  Axial coordinates
for a hexagonal lattice are thus simply ``(a,b)``, which is perhaps
more suitable for storage purposes than cubic coords.

Axial-Sum
=========

The sum remains important for honeycomb lattices, where points on the
lattice will have one of two different values of ``a+b+c`` based on
their parity;  nodes an even distance from the origin will have a sum
of zero, and nodes an odd distance from the origin will have a sum of 1.

Funnily enough, there is also a third possible sum with a different meaning:
A point with a sum of -1 or 2 (your choice; the sums are equivalent modulo 3)
lies directly in the center of one of the honeycombs.

'''

def cubic_to_axial(a,b,c): return (a, b)
def cubic_to_axialsum(a,b,c): return (a, b, a+b+c)
def axialsum_to_cubic(a,b,p): return (a, b, p-a-b)

def cubic_to_cart(a,b,c):
	'''
	Map the points to cartesian.

	Treats the 'a' vector as pointing SE, the 'b' vector as pointing NE,
	and the 'c' vector as pointing W.
	'''
	return (0.5*(a+b)-c, 0.5*(3**0.5)*(b-a))
def axialsum_to_cart(a,b,p):
	return cubic_to_cart(*axialsum_to_cubic(a,b,p))

def cubic_rotate_60(a,b,c): return (-b, -c, -a)
def cubic_rotations_60(a,b,c):
	return _unfold(cubic_rotate_60, (a,b,c), 6)

def cubic_rotate_120(a,b,c): return (c, a, b)
def cubic_rotations_120(a,b,c):
	return _unfold(cubic_rotate_120, (a,b,c), 3)

def axialsum_rotate_60(a,b,p): return (-b, a+b-p, -p)
def axialsum_rotations_60(a,b,p):
	return _unfold(axialsum_rotate_60, (a,b,p), 6)

def axialsum_rotate_120(a,b,p): return (p-a-b, a, p)
def axialsum_rotations_120(a,b,p):
	return _unfold(axialsum_rotate_120, (a,b,p), 3)

def _unfold(f, start, takeN):
	for _ in range(takeN):
		yield start
		start = f(*start)

