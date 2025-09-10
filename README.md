# CBoK - Career Body of Knowledge

## 本地开发调试步骤

一、安装依赖

宿主机推荐安装Python 3.9.6，配置虚拟环境后，在项目根目录执行如下命令。

```shell
  python3 requirements/install.py
```

安装成功后，检查关键依赖项如下：
- xadmin == 2.0.1
- Django == 2.2.27

二、迁移数据库

请将xadmin放在user后面迁移，示例如下，执行命令后会在对应的app目录下生成`migrations`文件夹
```shell
  python3 manage.py makemigrations user
  python3 manage.py makemigrations xadmin
  python3 manage.py makemigrations <其他app...>
```

迁移进数据库命令如下，如果迁移失败，请删除所有app下的`migrations`文件夹重试。
```shell
  python3 manage.py migrate
```

三、 本地安装CBoK（可选）

部分功能在本地使用，例如`bbx`中的`put_patch`，需要先在本地安装。这会在Python site中创建一个链接指向本地CBoK source。
```shell
  python3 -m site
  pip3 install -e .
```
