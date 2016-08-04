import logging
import operator
import functools
from termcolor import colored

# FIXME color in here is a total hack

class debug():
	def __init__(self, prefix='', member=False):
		self.prefix = prefix
		self.is_member = member

	def __call__(self, func):
		from functools import wraps
		@wraps(func)
		def wrapped(*args, **kw):
			args2show = args[1 if self.is_member else 0:]
			logging.debug(
				colored(self.prefix, 'green') +
				format_func_call(colored(func.__name__, 'yellow'), args2show, kw))
			return func(*args, **kw)
		return wrapped

def format_func_call(name, args, kw):
	argstrs = [repr(x) for x in args]
	kwstrs = ['{!s}={!r}'.format(k,v) for (k,v) in kw.items()]

	pat = '{}%s{}%s' % (colored('(', 'yellow'), colored(')', 'yellow'))
	sep = colored(', ', 'yellow')
	return pat.format(name, (sep.join(argstrs + kwstrs)))

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

def flat(iterable):
	'''
	Remove one level of nesting from a nested iterable.
	'''
	for x in iterable:
		yield from x

def window2(iterable):
	'''
	Iterate over overlapping pairs of successive elements.
	'''
	it = iter(iterable)
	prev = next(it)
	for x in it:
		yield prev, x
		prev = x

def partial_sums(iterable, zero=0, with_zero=False):
	if with_zero:
		iterable = flat([[zero], iterable])
	return scan(operator.add, iterable, initializer=zero)

def differences(iterable):
	for (old,new) in window2(iterable):
		yield new - old

def zip_exact(*args):
	'''
	zip iterables of equal length (or error).

	Warning: current implementation is not lazy and will fully traverse
	each iterable before returning. (soz)
	'''
	if len(args) == 0:
		return ()
	first,*rest = map(list, args)
	if any(len(x) != len(first) for x in rest):
		raise ValueError('mismatched lengths')
	return zip(first, *rest)

def intersperse(x, iterable):
	'''
	Turns ``[a,b,c,d,...e,f]`` into ``[a,x,b,x,...e,x,f]``.
	'''
	it = iter(iterable)
	first = next(it)
	yield first
	for elem in it:
		yield x
		yield elem

def memoize(func):
	'''
	Decorator to memoize a function.

	This caches the output of every call to the function, and returns the
	recorded result whenever the same set of arguments are seen again.
	'''
	# NOTE: written this way to be picklable without dill.
	wrapped = functools.partial(__memoize__inner, {}, func)
	wrapped = functools.wraps(func)(wrapped)
	return wrapped

def __memoize__inner(lookup, func, *args):
	if args not in lookup:
		lookup[args] = func(*args)
	return lookup[args]
