# -*- coding: utf-8 -*-
# Generated by Django 1.9.9 on 2016-11-21 02:54
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('gemcore', '0017_auto_20161109_2355'),
    ]

    operations = [
        migrations.AddField(
            model_name='tagregex',
            name='transfer',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='transfers', to='gemcore.Account'),
        ),
    ]
