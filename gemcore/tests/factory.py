# -*- coding: utf-8 -*-

import itertools

from decimal import Decimal

from django.contrib.auth import get_user_model

from gemcore.models import Account, Book, Entry, ParserConfig


User = get_user_model()


class Factory(object):

    def __init__(self):
        super(Factory, self).__init__()
        self.counter = itertools.count()

    def make_integer(self):
        return next(self.counter)

    def make_slug(self, prefix='slug'):
        return '%s-%s' % (prefix, self.make_integer())

    def make_user(self, username=None, password='test', **kwargs):
        if username is None:
            username = 'user-%s' % self.make_integer()
        return User.objects.create_user(
            username=username, password=password, **kwargs)

    def make_book(self, slug=None, name=None, users=None, **kwargs):
        i = self.make_integer()
        if name is None:
            name = 'Book %s' % i
        if slug is None:
            slug = 'book-%s' % i
        book = Book.objects.create(name=name, slug=slug, **kwargs)
        if users:
            for u in users:
                book.users.add(u)

        return book

    def make_account(
            self, name=None, slug=None, currency='USD', users=None, **kwargs):
        i = self.make_integer()
        if name is None:
            name = 'Account %s (%s)' % (i, currency)
        if slug is None:
            slug = 'account-%s-%s' % (currency, i)
        account = Account.objects.create(
            name=name, slug=slug, currency=currency, **kwargs)
        if users:
            for u in users:
                account.users.add(u)

        return account

    def make_tag_regex(self, regex, tag, account=None):
        if account is None:
            account = self.make_account()
        return account.tagregex_set.create(regex=regex, tag=tag)

    def make_entry(
            self, book=None, account=None, who=None, amount=Decimal('1.0'),
            what=None, country='AR', **kwargs):
        i = self.make_integer()
        if book is None:
            book = self.make_book()
        if account is None:
            account = self.make_account()
        if who is None:
            who = self.make_user()
        if what is None:
            what = 'Description of entry %i' % i
        tags = kwargs.pop('tags', [])
        result = Entry.objects.create(
            book=book, account=account, who=who, what=what, amount=amount,
            tags=tags, country=country, **kwargs)
        return result

    def make_parser_config(self, name=None, **kwargs):
        i = self.make_integer()
        if name is None:
            name = 'Parser %s' % i
        return ParserConfig.objects.create(name=name, **kwargs)
