from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from django.template.defaultfilters import slugify
from autoslug.fields import AutoSlugField
from taggit.managers import TaggableManager


CURRENCIES = [
    'ARS', 'EUR', 'USD', 'UYU', 'GBP',
]

TAGS = [
    'super', 'auto', 'servicios', 'impuestos',
]


class Book(models.Model):

    name = models.CharField(max_length=256)
    slug = AutoSlugField(populate_from='name', unique=True)
    users = models.ManyToManyField(User)

    def __str__(self):
        return self.name

    def latest_expenses(self):
        return self.expense_set.all().order_by('-when')[:5]

    def tags(self):
        result = defaultdict(int)
        for e in self.expense_set.filter(tags__isnull=False).distinct():
            for t in e.tags.all():
                result[t] += 1

        # templates can not handle defaultdicts
        return dict(result)


class Currency(models.Model):

    code = models.CharField(max_length=3, choices=[(c, c) for c in CURRENCIES])

    class Meta:
        verbose_name_plural = "Currencies"

    def __str__(self):
        return self.code


class Expense(models.Model):

    book = models.ForeignKey(Book)
    who = models.ForeignKey(User)  #, limit_choices_to={'who__in': 'book__users'})
    when = models.DateField(default=datetime.today)
    what = models.TextField()
    amount = models.DecimalField(
        decimal_places=2, max_digits=12,
        validators=[MinValueValidator(Decimal('0.01'))])
    currency = models.ForeignKey(Currency, default='ARS')

    tags = TaggableManager()

    def __str__(self):
        return '%s (by %s on %s)' % (self.what, self.who, self.when)
