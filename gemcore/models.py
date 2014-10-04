# -*- coding: utf-8 -*-

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from bitfield import BitField
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import connection, models
from django.utils.text import slugify
from django_countries import countries
from taggit.managers import TaggableManager


CURRENCIES = [
    'ARS', 'EUR', 'USD', 'UYU', 'GBP',
]
TAGS = [
    'bureaucracy', 'car', 'change', 'food', 'fun', 'health', 'house',
    'maintainance', 'other', 'rent', 'taxes', 'travel', 'utilities',
    'withdraw',
]


class Book(models.Model):

    name = models.CharField(max_length=256)
    slug = models.SlugField(unique=True)
    users = models.ManyToManyField(User)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        return super(Book, self).save(*args, **kwargs)

    def latest_entries(self):
        return self.entry_set.all().order_by('-when')[:5]

    def tags(self, entries=None):
        if entries is None:
            entries = self.entry_set.all()
        entries = ', '.join(str(e.id) for e in entries)
        result = {}
        if not entries:
            return result

        cursor = connection.cursor()
        for tag in TAGS:
            mask = getattr(Entry.flags, tag).mask
            cursor.execute(
                "SELECT COUNT(*) as entry_count FROM gemcore_entry "
                "WHERE gemcore_entry.book_id = %s "
                "AND gemcore_entry.id IN (%s) "
                "AND gemcore_entry.flags & %s = %s;" %
                (self.id, entries, mask, mask))
            tag_count = cursor.fetchone()[0]
            if tag_count:
                result[tag] = tag_count

        return result

    def years(self, entries=None):
        if entries is None:
            entries = self.entry_set.all()

        result = {}
        if entries.count() == 0:
            return result

        oldest = entries.order_by('when')[0].when.year
        newest = entries.order_by('-when')[0].when.year
        for year in range(oldest, newest + 1):
            year_count = entries.filter(when__year=year).count()
            if year_count:
                result[year] = year_count
        return result

    def countries(self, entries=None):
        if entries is None:
            entries = self.entry_set.all()

        entries = ', '.join(str(e.id) for e in entries)
        result = {}
        cursor = connection.cursor()
        cursor.execute(
            "SELECT country, COUNT(*) FROM gemcore_entry "
            "WHERE gemcore_entry.book_id = %s "
            "AND gemcore_entry.id IN (%s) "
            "GROUP BY gemcore_entry.country;" % (self.id, entries))
        result = dict(cursor.fetchall())
        return result

    def who(self, entries=None):
        if entries is None:
            entries = self.entry_set.all()
        result = defaultdict(int)
        for d in entries.values_list('who__username', flat=True):
            result[d] += 1
        return dict(result)


class Account(models.Model):

    name = models.CharField(max_length=256)
    slug = models.SlugField(unique=True)
    users = models.ManyToManyField(User)
    currency_code = models.CharField(
        max_length=3, choices=[(c, c) for c in CURRENCIES])

    class Meta:
        ordering = ('currency_code', 'name')

    def __str__(self):
        if self.users.count() == 1:
            result = '%s %s %s' % (
                self.currency_code, self.users.get().username, self.name)
        else:
            result = '%s shared %s' % (self.currency_code, self.name)
        return result

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        return super(Account, self).save(*args, **kwargs)


class Entry(models.Model):

    book = models.ForeignKey(Book)
    who = models.ForeignKey(User)
    when = models.DateField(default=datetime.today)
    what = models.TextField()
    account = models.ForeignKey(Account)
    amount = models.DecimalField(
        decimal_places=2, max_digits=12,
        validators=[MinValueValidator(Decimal('0.01'))])
    is_income = models.BooleanField(default=False, verbose_name='Income?')
    flags = BitField(flags=[(t.lower(), t) for t in TAGS], null=True)
    country = models.CharField(max_length=2, choices=countries, null=True)

    tags = TaggableManager()

    class Meta:
        unique_together = ('book', 'who', 'when', 'what', 'amount')
        verbose_name_plural = 'Entries'

    def __str__(self):
        return '%s (%s %s, by %s on %s)' % (
            self.what, self.amount, self.account, self.who, self.when)

    @property
    def currency(self):
        return self.account.currency_code
