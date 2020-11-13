# Generated by Django 2.2.16 on 2020-11-16 10:00

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('enterprise', '0115_enterpriseanalyticsuser_historicalenterpriseanalyticsuser'),
    ]

    operations = [
        migrations.AlterField(
            model_name='enterprisecustomerreportingconfiguration',
            name='data_type',
            field=models.CharField(choices=[('progress', 'progress'), ('progress_v2', 'progress_v2'), ('catalog', 'catalog'), ('engagement', 'engagement'), ('grade', 'grade'), ('completion', 'completion'), ('course_structure', 'course_structure')], default='progress', help_text='The type of data this report should contain.', max_length=20, verbose_name='Data Type'),
        ),
    ]
