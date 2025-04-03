from django.contrib.auth.models import AbstractUser
from django.db import models


class UserProfile(AbstractUser):

    class Meta:
        verbose_name = '用户信息'
        verbose_name_plural = verbose_name

    def __unicode__(self):
        return self.nick_name

    uuid = models.CharField(max_length=36, verbose_name='UUID')
    nick_name = models.CharField(max_length=10, verbose_name='昵称')
    gender = models.CharField(max_length=1, choices=(('1', '男'), ('2', '女')), verbose_name='性别')
    address = models.CharField(max_length=255, verbose_name='地址', null=True)
    avatar = models.ImageField(upload_to='image/%Y/%m', default='', max_length=255, verbose_name='头像')
