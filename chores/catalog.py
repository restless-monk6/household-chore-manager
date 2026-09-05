"""Standard household chores and their default point values.

Effort scale: 1 = under 5 min, 2 = 5-15 min, 3 = 15-30 min,
4 = 30-60 min or unpleasant, 5 = an hour or more.
"""

from .models import Category

CATALOG = [
    (Category.KITCHEN, "Unload dishwasher", 1),
    (Category.KITCHEN, "Wipe counters and table", 1),
    (Category.KITCHEN, "Take out rubbish", 1),
    (Category.KITCHEN, "Wash up / load dishwasher", 2),
    (Category.KITCHEN, "Cook dinner", 3),
    (Category.KITCHEN, "Mop kitchen floor", 3),
    (Category.KITCHEN, "Clean out the fridge", 3),
    (Category.KITCHEN, "Clean oven and stovetop", 4),
    (Category.BATHROOM, "Wipe sink and mirror", 1),
    (Category.BATHROOM, "Restock paper and soap", 1),
    (Category.BATHROOM, "Mop bathroom floor", 2),
    (Category.BATHROOM, "Clean the toilet", 3),
    (Category.BATHROOM, "Clean shower and bath", 4),
    (Category.LAUNDRY, "Start a load", 1),
    (Category.LAUNDRY, "Move load to dryer / hang out", 1),
    (Category.LAUNDRY, "Fold and put away a load", 2),
    (Category.LAUNDRY, "Change bed sheets", 2),
    (Category.LAUNDRY, "Iron a batch", 3),
    (Category.LIVING, "Tidy the living room", 2),
    (Category.LIVING, "Dust surfaces", 2),
    (Category.LIVING, "Vacuum one room", 2),
    (Category.LIVING, "Clean the windows", 3),
    (Category.LIVING, "Mop the floors", 3),
    (Category.LIVING, "Vacuum the whole house", 4),
    (Category.BEDROOMS, "Make the bed", 1),
    (Category.BEDROOMS, "Tidy your room", 2),
    (Category.BEDROOMS, "Sort and put away clothes", 2),
    (Category.OUTDOOR, "Water the plants", 1),
    (Category.OUTDOOR, "Bins out to the curb", 1),
    (Category.OUTDOOR, "Sweep the porch or driveway", 2),
    (Category.OUTDOOR, "Weed the garden", 4),
    (Category.OUTDOOR, "Rake the leaves", 4),
    (Category.OUTDOOR, "Wash the car", 4),
    (Category.OUTDOOR, "Mow the lawn", 5),
    (Category.PETS, "Feed the pet", 1),
    (Category.PETS, "Walk the dog", 2),
    (Category.PETS, "Clean litter box or cage", 2),
    (Category.ERRANDS, "Put away the groceries", 1),
    (Category.ERRANDS, "Do the grocery shop", 4),
]

POINTS_BY_NAME = {name: points for _, name, points in CATALOG}


def suggested_points(name):
    """Default point value for a chore name, or None if it isn't a standard one."""
    return POINTS_BY_NAME.get(name.strip())
