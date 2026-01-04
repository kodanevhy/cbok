# CBoK - Career Body of Knowledge

## 本地开发调试步骤

一、安装依赖

宿主机推荐安装Python 3.12.10，配置虚拟环境后，在项目根目录执行如下命令。

```shell
  pip3 install -r requirements.txt
```

安装成功后，检查关键依赖项如下：
- Django == 6.0

二、迁移数据库

如果没有数据库，可以使用Docker创建：
```shell
  docker run -d --name mariadb -e MYSQL_ROOT_PASSWORD=000000 -e MYSQL_DATABASE=cbok -p 3306:3306 -v mariadb_data:/var/lib/mysql mariadb:11.3
```

示例如下，执行命令后会在对应的app目录下生成`migrations`文件夹
```shell
  python3 manage.py makemigrations user
  python3 manage.py makemigrations <其他app...>
```

迁移进数据库命令如下，如果迁移失败，请删除所有app下的`migrations`文件夹重试。
```shell
  python3 manage.py migrate
```

三、生成配置文件

部分功能需要先声明配置，例如邮箱，用户应该尽量配置。若用户充分了解代码并明确暂时不需要相关功能，请将以下命令生成的 section 配置块整体注释掉，以不妨碍运行。
```shell
  python3 tools/generate_conf.py
```

四、 本地安装CBoK（可选）

部分功能在本地使用，例如`bbx`中的`put_patch`，需要先在本地安装。这会在Python site中创建一个链接指向本地CBoK source。
```shell
  python3 -m site
  pip3 install -e .
```
