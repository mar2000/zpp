from django import template

register = template.Library()

@register.filter
def subtract(value, arg):
    """Odejmuje arg od value"""
    return value - arg

@register.filter
def atan2_degrees(y, x):
    """Oblicza kąt w stopniach między punktami"""
    from math import atan2, degrees
    return degrees(atan2(y, x))
