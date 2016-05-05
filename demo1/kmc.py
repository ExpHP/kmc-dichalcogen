from bisect import bisect_left
from random import uniform
import operator

__all__ = ['weighted_choice']

# weighted_choice :: [(value, weight)] -> value
def weighted_choice(choices):

	# Filter out zeros to unify some edge cases
	# (namely, an empty list versus a nonempty list of zero weights)
	choices = [(v,w) for (v,w) in choices if w != 0.]
	if not choices:
		raise ValueError("Cannot choose from total weight of zero!")

	# Sort by weight to avoid precision loss in cumulative weights
	choices = sorted(choices, key=operator.itemgetter(1))
	values, weights = zip(*choices)
	if weights[0] < 0.:
		w,v = weights[0], values[0]
		raise ValueError("Negative weight {!s} for {!r}".format(w,v))

	cumul_weights = list(scan(operator.add, weights))
	total_weight = cumul_weights[-1]
	assert total_weight > 0. # already handled

	# DO EET
	x = uniform(0., total_weight)
	i = bisect_left(cumul_weights, x)
	return values[i]

def scan(function, iterable, initializer=None):
	'''
	Like ``reduce``, but yields partial results for each element.

	Arguments have same meaning as they do for ``reduce``.
	'''
	iterable = iter(iterable)
	if initializer is None:
		a = next(iterable)
		yield a
	else: a = initializer

	for x in iterable:
		a = function(a, x)
		yield a
