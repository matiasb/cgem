import operator

from collections import OrderedDict
from datetime import datetime, timedelta
from functools import reduce
from io import StringIO, TextIOWrapper
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core.urlresolvers import reverse
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_http_methods

import gemcore.parser
from gemcore.forms import (
    AccountBalanceForm,
    AccountTransferForm,
    BookForm,
    CSVExpenseForm,
    ChooseForm,
    CurrencyBalanceForm,
    EntryForm,
)
from gemcore.models import Account, Book, Entry


ENTRIES_PER_PAGE = 25
MAX_PAGES = 4


def filter_entries(request, book_slug):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)
    params = request.GET
    q = params.get('q')
    if q:
        entries = book.by_text(q)
    else:
        entries = book.entry_set.all()

    try:
        when = datetime.strptime(params.get('when'), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        when = None
        when_next = None
        when_prev = None
    else:
        when_next = when + timedelta(days=1)
        when_prev = when - timedelta(days=1)
        entries = book.entry_set.filter(when=when)

    try:
        year = int(params.get('year'))
    except (ValueError, TypeError):
        year = None
    else:
        entries = entries.filter(when__year=year)

    try:
        month = int(params.get('month'))
    except (ValueError, TypeError):
        month = None
    else:
        entries = entries.filter(when__month=int(month))

    who = params.get('who')
    if who:
        entries = entries.filter(who__username=who)

    country = params.get('country')
    if country:
        entries = entries.filter(country=country)

    account = params.get('account')
    if account:
        entries = entries.filter(account__slug=account)

    currency_code = params.get('currency_code')
    if currency_code:
        entries = entries.filter(account__currency_code=currency_code)

    used_tags = set(params.getlist('tag', []))
    if used_tags:
        tags = reduce(
            operator.or_,
            [getattr(Entry.tags, t.lower(), 0) for t in used_tags])
        entries = entries.filter(tags=tags)

    years = book.years(entries)
    months = OrderedDict(sorted({
        (d.month, d.strftime('%b'))
        for d in entries.values_list('when', flat=True)
    }))
    countries = [] if country else book.countries(entries)
    accounts = [] if account else book.accounts(entries)
    users = [] if who else book.who(entries)
    tags = book.tags(entries)

    context = dict(
        book=book, who=who, users=users, q=q, qs=urlencode(params),
        when=when, when_next=when_next, when_prev=when_prev,
        month=month, months=months, month_label=months.get(month),
        year=year, years=years, tags=tags, used_tags=used_tags,
        country=country, countries=countries,
        account=account, accounts=accounts, currency_code=currency_code,
    )
    return entries, context


@require_GET
@login_required
def home(request):
    books = request.user.book_set.all()
    if books.count() == 1:
        url = reverse('entries', args=(books.get().slug,))
    else:
        url = reverse('books')
    return HttpResponseRedirect(url)


@require_GET
@login_required
def books(request):
    books = request.user.book_set.all()
    context = dict(books=books)
    return render(request, 'gemcore/books.html', context)


@require_http_methods(['GET', 'POST'])
@login_required
def book(request, book_slug=None):
    book = None
    if book_slug:
        book = get_object_or_404(Book, slug=book_slug, users=request.user)

    if request.method == 'POST':
        form = BookForm(instance=book, data=request.POST)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(reverse(home))
    else:
        form = BookForm(instance=book)
    return render(request, 'gemcore/book.html', dict(form=form, book=book))


def _process_post_on_entries(request, entries, edit_account_form, context):
    assert request.method == 'POST', 'HTTP method should be POST'
    here = request.get_full_path()

    ids = [int(i) for i in request.POST.getlist('edit-entry')]
    if len(ids) == 0:
        messages.error(request, 'Invalid request, no entries selected.')
        return HttpResponseRedirect(here)

    entries = entries.filter(id__in=ids)
    if entries.count() != len(ids):
        messages.error(
            request, 'Invalid request, invalid choices for entries.')
        return HttpResponseRedirect(here)

    if 'change-account' in request.POST:
        if edit_account_form.is_valid():
            target = edit_account_form.cleaned_data['target']
            if not target:
                messages.error(
                    request, 'Invalid request, the target account is empty.')
            else:
                entries.update(account=target)
                msg = (', '.join(str(e) for e in entries), target)
                messages.success(
                    request, 'Entries "%s" changed to account %s.' % msg)
        else:
            messages.error(
                request, 'Invalid request for changing the account: %s' %
                         edit_account_form.errors)
        return HttpResponseRedirect(here)

    elif 'change-tags' in request.POST:
        template = 'gemcore/change-tags.html'
        raise NotImplementedError()

    elif 'merge-selected' in request.POST:
        template = 'gemcore/merge-entries.html'
        raise NotImplementedError()

    elif 'remove-selected' in request.POST:
        template = 'gemcore/remove-entries.html'

    else:
        raise Http404()

    context['entries'] = entries
    return render(request, template, context)


@require_http_methods(['GET', 'POST'])
@login_required
def entries(request, book_slug):
    entries, context = filter_entries(request, book_slug)
    book = context['book']
    accounts = Account.objects.by_book(book)
    currencies = sorted(set(accounts.values_list('currency_code', flat=True)))

    edit_account_form = ChooseForm(queryset=accounts)
    if request.method == 'POST':
        edit_account_form = ChooseForm(queryset=accounts, data=request.POST)
        return _process_post_on_entries(request, entries, edit_account_form, context)

    entries = entries.order_by('-when', 'what', 'id')

    paginator = Paginator(entries, ENTRIES_PER_PAGE)
    page = request.GET.get('page')
    try:
        entries = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        page = 1
        entries = paginator.page(page)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        page = paginator.num_pages
        entries = paginator.page(paginator.num_pages)
    else:
        page = int(page)

    if paginator.num_pages <= MAX_PAGES:
        start = 1
        end = paginator.num_pages
    else:
        half = MAX_PAGES // 2
        start = page - half
        end = page + half
        if start < 1 and end - start < paginator.num_pages:
            end = end - start + 1
            start = 1
        if end > paginator.num_pages and start > 1:
            start = start - (end - paginator.num_pages)
            end = paginator.num_pages

    page_range = range(start, end + 1)
    context.update(dict(
        entries=entries, page_range=page_range, start=start, end=end,
        edit_account_form=edit_account_form,
        account_balance_form=AccountBalanceForm(queryset=accounts),
        currency_balance_form=CurrencyBalanceForm(choices=currencies),
    ))
    return render(request, 'gemcore/entries.html', context)


@require_http_methods(['GET', 'POST'])
@login_required
def entry(request, book_slug, entry_id=None):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)
    entry = None
    if entry_id:
        entry = get_object_or_404(Entry, book=book, id=entry_id)

    context = dict(book=book, entry=entry)
    if request.method == 'POST':
        form = EntryForm(instance=entry, book=book, data=request.POST)
        if form.is_valid():
            entry = form.save(book=book)
            # decide where to redirecr next
            kwargs = dict(book_slug=book_slug)
            if 'save-and-new' in request.POST:
                url = reverse('add-entry', kwargs=kwargs)
            elif 'save-and-new-same-date' in request.POST:
                url = reverse('add-entry', kwargs=kwargs)
                url += '?when=' + entry.when.isoformat()
            elif 'save-and-edit' in request.POST:
                kwargs['entry_id'] = entry.id
                url = reverse('entry', kwargs=kwargs)
            elif 'save-and-go-back' in request.POST:
                url = reverse('entries', kwargs=kwargs)
            else:  # could be a remove
                url = reverse('entries', kwargs=kwargs)
            messages.success(
                request, 'Entry "%s" successfully processed.' % entry)
            return HttpResponseRedirect(url)
    else:
        initial = {}
        if entry is None:
            try:
                last_entry = Entry.objects.filter(
                    who=request.user, book=book).latest('when')
                account = last_entry.account
            except Entry.DoesNotExist:
                account = None

            q = request.GET.get('q', '')
            initial = dict(who=request.user, account=account, what=q)
            when = request.GET.get('when')
            if when:
                initial['when'] = when

        form = EntryForm(instance=entry, book=book, initial=initial)
        if entry:
            try:
                context['entry_prev'] = entry.get_previous_by_when()
            except Entry.DoesNotExist:
                pass
            try:
                context['entry_next'] = entry.get_next_by_when()
            except Entry.DoesNotExist:
                pass

    context['form'] = form
    return render(request, 'gemcore/entry.html', context)


@require_http_methods(['GET', 'POST'])
@login_required
def entry_remove(request, book_slug, entry_id=None):
    entries, context = filter_entries(request, book_slug)
    if request.method == 'GET':
        entries = entries.filter(id=entry_id)
    elif request.method == 'POST':
        entries = entries.filter(id__in=request.POST.getlist('entry'))
    else:
        entries = Entry.objects.none()

    if not entries:
        raise Http404()

    if request.method == 'POST':
        if 'yes' in request.POST:
            msg = ', '.join(str(e) for e in entries)
            entries.delete()
            messages.success(request, 'Entries "%s" removed.' % msg)
        else:
            messages.warning(request, 'Removal of entries cancelled.')
        return HttpResponseRedirect(
            reverse('entries', args=(book_slug,)) + '?' + context['qs'])

    return render(
        request, 'gemcore/remove-entries.html', dict(entries=entries))


@require_http_methods(['GET', 'POST'])
@login_required
def load_from_file(request, book_slug):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)

    if request.method == 'POST':
        form = CSVExpenseForm(
            book=book, data=request.POST, files=request.FILES)
        if form.is_valid():
            csv_file = form.cleaned_data.get('csv_file')
            if csv_file:
                # Hack around: "iterator should return strings, not bytes
                # (did you open the file in text mode?)"
                csv_file.readable = lambda: True
                csv_file.writable = lambda: False
                csv_file = TextIOWrapper(csv_file, encoding='utf-8')
                # end hack
            else:
                csv_content = form.cleaned_data.get('csv_content')
                csv_file = StringIO(csv_content)
                csv_file.name = ''

            account = form.cleaned_data['account']
            csv_parser = getattr(gemcore.parser, account.parser)
            result = csv_parser().parse(
                csv_file, book=book, user=request.user, account=account)
            success = len([e for e in result['entries'] if e])
            error = sum(len(i) for i in result['errors'].values())
            if not error:
                messages.success(
                    request, 'File %s successfully parsed (%s entries added).'
                    % (csv_file.name, success))
            elif success:
                messages.warning(
                    request,
                    'File %s partially parsed (%s successes, %s errors).' %
                    (csv_file.name, success, error))
            else:
                messages.error(
                    request, 'File %s could not be parsed (%s errors).' %
                    (csv_file.name, error))

            if error:
                for e, errors in result['errors'].items():
                    error_msg = ', '.join(str(i) for i in errors)
                    messages.error(request, '%s: %s' % (e, error_msg))

            return HttpResponseRedirect(
                reverse('entries', kwargs=dict(book_slug=book_slug)))
    else:
        form = CSVExpenseForm(book=book)

    context = dict(form=form)
    return render(request, 'gemcore/load.html', context)


@require_http_methods(['GET', 'POST'])
@login_required
def account_transfer(request, book_slug):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)

    if request.method == 'POST':
        form = AccountTransferForm(book, request.POST)
        if form.is_valid():
            source_account = form.cleaned_data.get('source_account')
            source_amount = form.cleaned_data.get('source_amount')
            target_account = form.cleaned_data.get('target_account')
            target_amount = form.cleaned_data.get('target_amount')
            when = form.cleaned_data.get('when')
            what = form.cleaned_data.get('what')
            country = form.cleaned_data.get('country')
            tags = Entry.tags.change

            Entry.objects.create(
                book=book, who=request.user, when=when,
                what=what + ' (source)',
                account=source_account, amount=source_amount,
                is_income=False, country=country, tags=tags,
            )
            Entry.objects.create(
                book=book, who=request.user, when=when,
                what=what + ' (target)',
                account=target_account, amount=target_amount,
                is_income=True, country=country, tags=tags,
            )

            return HttpResponseRedirect(
                reverse('entries', kwargs=dict(book_slug=book_slug)))
    else:
        initial = {}
        when = request.GET.get('when')
        if when:
            initial['when'] = when
        form = AccountTransferForm(book, initial=initial)

    context = dict(form=form)
    return render(request, 'gemcore/transfer.html', context)


@require_http_methods(['GET', 'POST'])
@login_required
def balance(
        request, book_slug, account_slug=None, currency_code=None,
        start=None, end=None):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)
    accounts = Account.objects.by_book(book)
    currencies = sorted(set(accounts.values_list('currency_code', flat=True)))

    if request.method == 'POST':
        if 'get-account-balance' in request.POST:
            form = AccountBalanceForm(queryset=accounts, data=request.POST)
        elif 'get-currency-balance' in request.POST:
            form = CurrencyBalanceForm(choices=currencies, data=request.POST)
        else:
            raise Http404()

        if form.is_valid():
            source = form.cleaned_data['source']
            kwargs = dict(book_slug=book.slug)
            if isinstance(source, Account):
                kwargs['account_slug'] = source.slug
            else:
                kwargs['currency_code'] = source
            url = reverse('balance', kwargs=kwargs)
            start = form.cleaned_data['start']
            end = form.cleaned_data['end']
            qs = {}
            if start:
                qs['start'] = start
            if end:
                qs['end'] = end
            if qs:
                url += '?' + urlencode(qs)
            return HttpResponseRedirect(url)

    chosen_accounts = None
    if account_slug:
        chosen_accounts = accounts.filter(slug=account_slug)
    elif currency_code:
        chosen_accounts = accounts.filter(currency_code=currency_code)

    if chosen_accounts is not None and not chosen_accounts.exists():
        raise Http404

    balance = None
    if chosen_accounts:
        start = request.GET.get('start')
        end = request.GET.get('end')
        if start:
            start = datetime.strptime(start, '%Y-%m-%d').date()
        if end:
            end = datetime.strptime(end, '%Y-%m-%d').date()
        # book.balance will only return entries for the book, which we ensured
        # request.user has access to
        balance = book.balance(chosen_accounts, start, end)

    account_balance_form = AccountBalanceForm(
        queryset=accounts,
        initial=dict(source=account_slug, start=start, end=end))
    currency_balance_form = CurrencyBalanceForm(
        choices=currencies,
        initial=dict(source=currency_code, start=start, end=end))
    context = {
        'balance': balance,
        'book': book,
        'account_slug': account_slug,
        'currency_code': currency_code,
        'account_balance_form': account_balance_form,
        'currency_balance_form': currency_balance_form,
    }
    return render(request, 'gemcore/balance.html', context)
