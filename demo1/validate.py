
from tabulate import tabulate
from collections import Counter

'''
Collects common patterns in validation functions.

Some of these offer very similar functionality to the ``assertSomething``
methods provided on ``unittest.TestCase``, but those methods were not
designed with large objects in mind. (these will just print out a single
mismatch rather they trying to string-diff the whole thing)
'''

# For small values only (those which can be easily printed)
def validate_equal(a, b):
	if a != b:
		raise AssertionError('{!r} != {!r}'.format(a, b))

def validate_no_dupes(it, name='sequence', item='item'):
	it = list(it)
	if len(it) != len(set(it)):
		dupe = Counter(it).most_common()[0][0]
		raise AssertionError('duplicate {!s} in {!s}: {!r}'.format(item, name, dupe))

def validate_dict(d1, d2, name1='left', name2='right', key='key', value='value'):
	validate_set(set(d1), set(d2), name1, name2, item=key)

	for k in d1:
		if d1[k] != d2[k]:
			# (note: the blank tabulate entries are to make a small indent)
			head = '{!s} mismatch for {!s}: {!r}'.format(value, key, k)
			table = tabulate([['', name1, repr(d1[k])], ['', name2, repr(d2[k])]], tablefmt='plain')
			raise AssertionError('%s\n%s' % (head,table))

def validate_set(set1, set2, name1='left', name2='right', item='item'):
	diff = set1 - set2
	if diff:
		raise AssertionError("{!s} only in {!s}: {!r}".format(item, name1, diff.pop()))

	diff = set2 - set1
	if diff:
		raise AssertionError("{!s} only in {!s}: {!r}".format(item, name2, diff.pop()))


