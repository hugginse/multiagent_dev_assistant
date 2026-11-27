# sample_repo

演示用迷你订单服务（`orderlib`）：供 multiagent_dev_assistant 的任务套件出题
（bugfix / feature / refactor）。自带 pytest 基线，**全部测试应为绿**。

## 结构

```
sample_repo/
├── orderlib/
│   ├── __init__.py
│   ├── models.py          # Order / OrderItem / Status
│   ├── pricing.py         # 小计、折扣、运费
│   ├── inventory.py       # 库存扣减与回滚
│   ├── orders.py          # 下单 / 取消 / 查询
│   ├── exceptions.py      # 领域异常
│   └── utils.py           # id 生成、时间工具
├── tests/
│   ├── test_models.py
│   ├── test_pricing.py
│   ├── test_inventory.py
│   ├── test_orders.py
│   └── test_utils.py
├── pyproject.toml
└── README.md
```

## 约定

- 金额一律用 **分（int）** 存储，禁止 float
- 领域错误抛 `orderlib.exceptions` 下的类型，不返回 None 表示失败
- 公共 API 从 `orderlib` 顶层导出

## 运行测试

```bash
python -m pytest -q
```
