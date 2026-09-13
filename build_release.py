# -*- coding: utf-8 -*-
"""一键发布脚本：python build_release.py [--skip-verify]

发布格式为便携 zip（NSIS/Inno Setup 工具链在本机不可用，安装包暂缓）。
流程 = 验证门禁 → PyInstaller 打包 → 便携 zip → SHA256 清单 → 发布记录。

产出 release/ 目录：
  ├── 卡卡颂.exe                      单文件 EXE（windowed，无控制台）
  ├── 卡卡颂_v{V}_win64_便携版.zip    便携包（EXE + 说明文档）
  ├── 使用说明.txt / 版本说明.txt
  └── SHA256SUMS.txt                  全部产物的完整性清单
并在 docs/发布记录.md 自动登记版本/日期/文件与哈希。
"""
from __future__ import annotations

import datetime
import hashlib
import io
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
RELEASE = os.path.join(ROOT, "release")
DOCS = os.path.join(ROOT, "docs")
ICON = os.path.join(ROOT, "assets", "app.ico")
EXE_NAME = "卡卡颂"
MANIFEST = "SHA256SUMS.txt"


def _version() -> str:
    """版本号单一来源：game/__init__.__version__。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "game_init", os.path.join(ROOT, "game", "__init__.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.__version__


VERSION = _version()


def make_icon() -> str:
    """用起始牌画面生成多尺寸 .ico。"""
    from PIL import Image
    from game import tile_data
    from game.art import render_tile
    img = render_tile(tile_data.by_id("MR-start"), 0).convert("RGB")
    img = img.resize((256, 256), Image.LANCZOS)
    img.save(ICON, format="ICO", sizes=[(16, 16), (32, 32), (48, 48),
                                        (64, 64), (128, 128), (256, 256)])
    return ICON


def write_docs() -> None:
    usage = """卡卡颂 · 桌游模拟器  使用说明
================================

一、启动
  双击「卡卡颂.exe」→ 选择模式：
    · 单机对局：2-6 人热座或人机对战（可自由搭配人数与 AI 难度）
    · 建立联机房间：选总人数/AI 数/房主名，创建后窗口显示本机 IP 与端口
    · 加入联机房间：同一局域网输入主机 IP + 端口 + 名字

二、操作
  放置地牌：点击黄色高亮格（当前朝向的合法位置）；悬停显示预览
  旋转地牌：「↻ 旋转」按钮或按 R 键
  无处可放：「弃牌重抽」按钮（需全员同意）
  部署随从：放牌后点击牌上黄色圆钮（骑士/强盗/僧侣/农夫），或「跳过部署」
  终局结算：牌堆摸空自动结算（含农场），弹出胜负与明细

三、联机说明
  · 房主默认端口 37241（被占用时自动换端口，以窗口显示为准）
  · 好友加入：游戏内「加入联机房间」填主机 IP + 端口
  · 断线玩家由主机代打推进；断线后同名重新加入可恢复座位

四、规则
  基础版 72 张地牌完整实现，规则依据 CAR v7.4（docs/S-CAR_v7.4.pdf）。
  计分口径：城市 2 分/牌+2 分/旗帜；道路 1 分/牌；修道院 9 分；
  终局农场按第三版规则（完成城市 3 分/个）；多数者得分、平局均得。

五、常见问题
  · 首次启动稍慢（单文件解压），属正常现象
  · Windows SmartScreen 提示「未知发布者」：点「更多信息」→「仍要运行」
  · 杀毒软件误报：本程序为本地 Python 打包，可添加信任
"""
    note = """卡卡颂 · 桌游模拟器  版本说明
================================

v0.15.2（2026-09）
  - 【新】开局设置与建房对话框的扩展开关改为可折叠面板：默认折叠只占一行
    （标题显示已选数量），点开限高滚动并附全选/清空；展开后窗口自动上移，
    20 个扩展开关在小屏上不再顶出屏幕
  - 验证：verify_ui 新增对话框回归（默认折叠/展开/选择回传/不超屏），
    窗口映射断言加事件泵，消除偶发抖动

v0.9.0（2026-09）
  - 【新】发布管线增强（M17）
    · 一键发布内置验证门禁：语法 → 牌面/随机对局 → UI 全流程，
      任一失败即中止构建（python build_release.py --skip-verify 可跳过）
    · release/ 附带 SHA256SUMS.txt 完整性清单；docs/发布记录.md 自动登记
      版本/日期/文件与哈希
    · 发布格式为便携 zip（本机无 NSIS/Inno Setup 工具链，安装包暂缓；
      解压即用、无安装痕迹）

v0.15.1（2026-09）
  - 修复：改建城堡时多数方多枚随从只留 1 枚作标记，其余被吞（全开扩展
    随机对局终局米宝不守恒）
  - 修复：驻塔在普通米宝耗尽、仅剩大型米宝时仍按普通米宝扣库存

v0.15.0（2026-09）
  - 【新】命运之轮（The Wheel of Fortune，M21 收官，CAR 页 109-116）
    · 大轮盘起始牌替代修道院起始牌（边界连通近似：北/东城段 + 南/西路）
    · 官方"仅混入 19 张命运图腾牌"变体：基础拓扑 + 图腾数字 1-3
      （数字分布按 CAR 页 114 近似重建）
    · 抽到命运牌先转轮盘再放牌（脚注 330）：猪顺时针走图腾数字格 →
      触发停驻扇区事件——幸运（当前玩家 +3）/ 税收（骑士数+城旗数，脚注
      331）/ 饥荒（每农夫按草场价值计分，无多数要求、粮仓不算，脚注
      332/333）/ 风暴（+1/供给随从）/ 审判（+2/修士）/ 瘟疫（各玩家依次
      收回一名场上随从，当前玩家先行）
    · 王冠位 10 个（幸运2/瘟疫2/审判2/风暴1/饥荒1/税收2）：部署阶段代替
      随从上架；猪停扇区的王冠随从计分归还（1 位扇区 3 分、2 位扇区独占
      6/双人各 3）；龙与瘟疫均不可及；终局归还
  - 扩展开关 20 项（M1–M21 全部 20 个扩展/模块齐备）；联机消息 plague，
    王冠位走 deploy 消息；快照携带猪位/王冠/瘟疫状态
  - 验证：新增 5 个轮盘黄金用例（总 86）；--wheel 随机 8 局；联机场景 8
    升级十一扩展同开
  - 修复：verify_network 驱动中瘟疫/牧羊处理器位于回合门之后（非当前回合
    玩家的决策者永远轮不到——轮盘开局瘟疫阶段挂死）

v0.14.0（2026-09）
  - 【新】扩展九「山丘与羊」（Hills & Sheep，M21，CAR 页 102-109，18 张新牌）
    · 山丘（8 张）：放置时自动从牌堆抽一张暗牌垫底（不计特征，CAR 页 104）；
      平局破缺——平局中恰一方有山丘随从 → 独得全场（双方都有则照旧均分，
      脚注 321）；终局计分同样适用
    · 牧羊人（每色 1，非随从）：可部署到刚放牌的草场段（草场有农夫亦可、
      有其他牧羊人不可），部署即抽一张羊/狼令牌；狼 → 全草场羊回袋、
      牧羊人回家；此后本放置延伸己方草场时可选「扩群再抽 / 入圈计分」
      （入圈=全草场各牧羊人得总羊数，脚注 317/318 牧羊行动先于龙移动）；
      同草场多牧羊人共享羊群；龙吞牧羊人连同羊（脚注 325）；终局不计分
    · 葡萄园（2 张）：修院完成时周围 8 格每座葡萄园 +3 分（终局不生效）
    · 特殊牌：城侧/田侧半边双段牌——一条边覆盖两个段，邻牌放置时与全部
      覆盖段合并（棋盘层 city/farm_segs_at_edge 列表化）；页 107 两特殊牌
      相邻"不相连"特例依赖半边方位，整边模型近似为相连（已注记）
  - 扩展开关 19 项；快照携带山丘/牧羊人/羊令牌（联机场景 8 同开）
  - 修复：羊袋无条件初始化消耗 RNG 改变基础牌堆次序（河流回归被带偏）
  - 验证：新增 8 个山丘羊黄金用例（总 81，含半边双段合并与守恒断言）；
    --hs 随机 8 局 + 迷你+塔+山丘羊合并 6 局

v0.13.0（2026-09）
  - 【新】扩展四「塔」（The Tower，M21，CAR 页 51-57，18 张新牌）
    · 塔基石牌按常规方式放置（CAR v7.4 无邻接限制；横竖射线只用于抓人）
    · 部署阶段三选一替代动作：建塔块（未完工塔/空塔基，可顺手抓一名
      射线内随从——射程=塔块数，可跨空格与塔；自己人直接回供给）/
      驻塔随从（塔完工，留至终局，可被龙吞或他塔抓走）/ 花 3 分赎金
      买回人质（己方 -3、对方 +3，当回合即可部署；每回合一次）
    · 互扣人质自动对换归还；被抓随从的特征若其建造者/猪失去保护一并
      归还（脚注 123）；城堡内随从天然免疫（已下场）；龙吞驻塔随从
    · 塔块限量：2 人各 10 / 3 人 9 / 4 人 7 / 5 人 6 / 6 人 5
  - 扩展开关 18 项；快照携带塔/人质/赎金状态；联机消息 tower
    （建塔/驻塔/赎金三动作）；AI/服务器代打全覆盖
  - 验证：新增 6 个塔黄金用例（总 73，含射程成长与互扣对换）；--tower
    随机 8 局（含人质守恒）；联机场景 8 扩为迷你合集+塔同开
  - 更正：M21 排期笔记中"塔牌只能横竖相邻放置"系误记，CAR v7.4 无此规则

v0.12.0（2026-09）
  - 【新】迷你扩展合集八件套（M20，CAR 页 120-200，共 53 张新牌）
    · 围攻（6 张）：被围城完成 1 分/（牌+旗、大教堂 2），终局 0 分；
      骑士可经 8 邻修道院（含修道院牌/教堂）脱困，每回合一名
    · 节日（10 张）：放置后可收回场上任一己方图元（代替部署，或都不做）
    · 金矿（8+1 张）：金矿牌落 2 块金（第二块自选邻牌）；完成特征上的
      金块归多数者（平局从主动玩家起轮流取，修院含 9 格）；城堡回响可索
      vicinity 金（脚注 396）；终局按 1-3:1 / 4-6:2 / 7-9:3 / 10+:4 折分
    · 法师与女巫（8+1 张）：法师牌后必落/移法师或女巫于未完成城/路；
      完成/终局时法师 +1 分/牌、女巫减半向上取整；随计分离场
    · 强盗（8+1 张）：强盗牌后各玩家可把强盗放上对手随从所在计分格；
      他人得分时偷走一半（向上取整）后回供给；"贼不偷贼"随行规则；
      终局在轨强盗各 +3
    · 麦田怪圈（6 张 + 迷你随附 3 张）：放置后主动玩家选 A 可部署同伴
      到己方同类型随从所在特征 / B 全体必须收回一名同类型随从
    · 隧道（4 张）：每回合可占一个隧道口；同色双令牌把两条路地下接通
      （只计可见段，口未接通路永不完成）；令牌永久留场
    · 幽灵：每色 1 枚第二普通随从，可部署到刚放牌的第二个特征
  - 扩展开关增至 17 项（单机/建房）；快照携带法师/女巫/强盗轨道/金块/
    隧道令牌/怪圈与幽灵状态（联机新场景 8 全程同步）
  - AI/服务器代打覆盖全部新阶段；联机消息 gold/mw/tunnel/crop/robber/escape
  - 验证：新增 11 个 M20 黄金用例（总 67，含幽灵节点叠放归还修复的
    防回归）；迷你合集随机 12 局（令牌/米宝/幽灵守恒断言）+ 联机场景 8

v0.11.0（2026-09）
  - 【新】扩展七「桥、城堡与集市」（Bridges, Castles and Bazaars，M19，CAR 页 92-101）
    · 木桥（每色 3 座）：跨越田地把两段路接通；桥下农场/城市不分割；一回合
      一座，可建在刚放的牌或正交相邻牌上；放置需要桥时自动建造，部署阶段
      也可自愿建造（联机已通路，脚注 292/294）
    · 城堡（每色 3 座）：两牌半圆小城完成时占据者可改建（4 分换成 9 分）；
      其后 6 邻格内任一修道院/城/路/城堡在更晚回合完成时，城堡主按同等
      分数再得一次；无主完成的特征也回响（脚注 307）；农场计城堡 4 分
      （带猪 5）；国王不数城堡
    · 集市（8 张）：打出集市牌后按人数翻牌拍卖——下家选牌出价（可为 0），
      其余依次加价或放弃；选牌者按最高价买下或卖给最高者；最后一张免费；
      购入的牌从触发者下家起依序放置，不连锁触发拍卖
  - 修复：修道院牌两侧为路时放置会误自动建桥（桥数耗尽时直接崩溃服务器
    线程——联机客人断线、终局不一致的根因）；服务器单条消息异常改为
    error 回复，不再杀死座位线程
  - 修复：快照缺待决城堡队列 → 联机时改建城堡的询问不弹出（重建副本
    队列为空）；快照新增 castle_queue，重建副本完整恢复
  - 扩展开关 9 项齐备；快照携带桥/城堡/集市状态（含断线重连重建）
  - 验证：新增 6 个 M19 黄金用例（共 56，含修道院误建桥防回归）；联机
    场景 7 升级九扩展同开完整对局（龙阶段 120+ 帧同步）

v0.10.0（2026-09）
  - 【新】扩展六「国王与强盗男爵」+ 三个配套小扩展（M18，CAR 页 69-87）
    · 河流 II（12 张）：泉源/岔流/火山湖替代起始修道院，蛇形连通开局；
      龙在河流末张降临并直接开始正常对局；猪倌农场终局 +1 分/城
    · 国王与强盗男爵（5 张新牌）：更大完成城/路转移标记；终局持有者
      1 分/场上完成城（含伯爵城）/完成路
    · 教堂与异端（5 张新牌）：教堂挑战 8 邻修道院，先完成者 9 分、
      对方无分归还；同放置双完成均得分；禁邻接两座对手建筑
    · 卡卡颂伯爵：4×3 城块起始（12 牌大城开局即完整，计国王与农场）；
      四区等候随从——触发计分未得分者可进城部署（可移伯爵）；
      特征计分前重部署回合（放置者左侧起轮询一圈，伯爵所在区封锁）；
      终局轮候移入有利特征（脚注 226）；龙禁入城块、传送门禁入大城
  - 修复：通用 deploy() 不路由特殊图元（市长/粮仓/马车/建造者/猪/仙女/公主）
    ——本地 UI 点击与服务器 AI 代打选中即崩（M15/M16 遗留，随机局掩盖）
  - 扩展开关 8 项齐备（单机/建房）；快照携带国王/挑战/伯爵/河流状态
  - 验证：新增 15 个 M18 黄金用例（共 50）；联机场景 7 升级八扩展同开
    完整对局（龙阶段 103 帧同步）

v0.9.1（2026-09）
  - 修复：联机龙移动消息未被服务器分发（报"未知消息 drag"）——P&D 扩展
    联机局中人类玩家无法移动龙；龙阶段改按轮值决定者校验（非当前回合玩家亦可动）
  - 验证补强（工程欠账清偿）：validate() 补齐四扩展张数断言（CAR 页
    30/34/40/57：18/24/30/12 张）与扩展牌段一致性全检（此前仅检基础版）
  - verify_network 新增场景 7「四扩展同开完整联机对局」：覆盖龙阶段帧同步
    与全部特殊部署类型（仙女/公主/传送门/市长/粮仓/马车/建造者/猪）

v0.8.0（2026-09）
  - 【新】扩展四「修道院与市长」（Abbey & Mayor，M16）：12 张新牌
    · 修道院牌（6）：可放任意相邻空格（无需边匹配），完成同修道院 9 分
    · 市长（每色 1）：部署到无骑士的城；强度=城内旗帜数（0 旗不得分）
    · 粮仓（每色 1）：部署到农场即结算（农夫归还、多数者 3 分/城+猪 4）；龙不吃
    · 马车（每色 1）：城/路完成后自动移到相邻未完成特征（可连续）
    · 多数判定特殊化：城特征支持市长加权（普通 1/大 2/市长=段旗数）
  - 扩展开关与其他扩展叠加（单机/建房 UI 全部勾选项齐备）
  - 快照携带市长/马车/粮仓状态；AI 具备市长/粮仓/马车部署决策
  - 验证：4 个 A&M 黄金用例；四扩展同开随机对局回归

v0.7.0（2026-09）
  - 【新】扩展三「公主与龙」（The Princess & the Dragon，M15）：30 张新牌
    · 火山（6）：放置后龙降临该牌，本回合不能部署任何图元
    · 龙牌（12）：部署后进入龙移动阶段——共 6 步，从当前玩家起轮流各移 1 步；
      龙进入的牌上全部随从/建造者/猪被吞（归还主人、无分）；仙女牌与已访问牌禁入；死路提前结束
    · 仙女（中立）：不部署图元时可移到己方跟随者所在牌——龙禁入、回合开始 +1、
      特征完成时 +3（独立结算）；跟随者归还后失去绑定
    · 公主（6）：延伸含骑士的城时可移走其中一个骑士（含对手），该回合不能再部署
    · 传送门（6）：随从可部署到场上任意合法空段（含远处）
    · 特殊牌：城内修道院（骑士或僧侣二选一）、全田火山+修道院
  - 快照携带仙女/龙状态（联机同步）；AI 具备龙移动/仙女/公主决策
  - 验证：7 个 P&D 黄金用例；含三扩展随机对局回归（吞噬/仙女/公主路径覆盖）

v0.6.0（2026-09）
  - 【新】架构与性能（M14）
    · ui.py（1456 行）拆分：ui_common（常量/绘制）/ ui_dialogs（对话框）/
      ui.py（App 1072 行）——game.ui 公开名字不变，验证脚本零改动
    · 棋盘渲染分层：静态层（牌/米宝/图元）指纹缓存，动态层（高亮/锚点/幽灵）每帧重绘
      60 牌棋盘实测重绘耗时下降 42%（3.37ms → 1.95ms）
    · 修复：进行中的计分飘字不再被全量重绘吞掉

v0.5.0（2026-09）
  - 【新】体验增强（M13，第二期开始）
    · 计分飘字动画：特征完成时在其位置弹出"+N"上浮渐隐（本地/联机均生效）
    · 窗口尺寸/位置记忆：关闭保存、启动恢复
    · 游戏内帮助按钮「?」：操作说明弹窗
  - 计分事件携带特征坐标（本地与联机协议同步）

v0.4.0（2026-09）
  - 【新】扩展 AI（M11）
    · hard 档 1 步前瞻：快照重建模拟 top-6 候选，按即时分差+特征潜力选步
    · 特征潜力感知：客栈路/大教堂城未完成终局 0 分 → 潜力减半（风险建模）
    · 商品城完成收益计入放置评估
  - AI 基准（30 局梯度）：hard 对 normal 胜率 95%（基础版）/ 87%（双扩展），
    对 easy 100%，梯度断言门槛提升至 65%

v0.3.1（2026-09）
  - 【新】联机体验增强（M10）
    · 断线自动重连：同名重连保留座位并补发快照（最多 10 次，界面显示进度）
    · 延迟显示：顶栏实时显示与主机的往返延迟
    · 房主可在大厅移出人类玩家（对局中不可移出）
  - 修复：重连握手将补发快照误当应答消费，导致座位号丢失、重连后不行动

v0.3.0（2026-09）
  - 【新】扩展二「商人与建造者」（Traders & Builders）：24 张新牌（每张带图元）
    · 贸易商品（酒9/谷6/布5）：城市完成时由完成者收全部商品；
      终局三种商品各自最多者各得 10 分（平局均得）
    · 建造者（每色 1）：部署到含己随从的城/路段；延伸该特征时获得双回合（无连锁）
    · 猪（每色 1）：部署到含己农夫的农场；终局猪主人（需为多数/平局）4 分/城
    · 特殊牌：桥（两路贯通、四段独立田）、修道院分隔三路、三段独立田等
  - 扩展开关与客栈/大教堂可叠加（牌堆最多 113 张）；联机建房同步支持
  - UI：商品/猪/建造者程序化图标、玩家货物计数、双回合提示
  - 验证：4 个 T&B 黄金用例；含扩展随机对局/AI 对战回归

v0.2.0（2026-09）
  - 【新】扩展一「客栈与大教堂」（Inns & Cathedrals）：18 张新牌
    · 客栈路：完成 2 分/牌，未完成终局 0 分（只影响紧邻路段）
    · 大教堂城：完成 3 分/（牌+旗帜），未完成终局 0 分
    · 大型米宝：每色 1 个，多数判定按 2 计（不翻倍得分），农民版同农夫
    · 特殊牌：四段独立城、修道院分隔道路、交叉口分隔道路
  - 扩展开关：单机/联机建房均可勾选；基础版行为完全不变
  - 联机协议与快照携带扩展配置，主机权威自动同步
  - AI 识别客栈/大教堂计分（含风险：不完成则 0 分）
  - 素材：客栈（湖面小屋）与大教堂（尖塔）程序化图标
  - 验证：新增 6 个扩展黄金用例；含扩展随机对局/联机局回归

v0.1.1（2026-09）
  - hard AI 显著增强：多数感知完成评估（不送分）、邻格修道院完成感知、
    修道院估值分级、低随机扰动（基准：对 normal 胜率 60%，对 easy 100%）
  - 弃牌重抽加确认弹窗（规则：需全员同意）
  - 计分板过 0 时显示玩家实际总分（50/100 分牌提示）
  - 当前朝向不可行时旋转按钮变红提醒；中键/右键拖动平移棋盘
  - 联机大厅 AI 补位说明；房主一键复制联机地址

v0.1.0（2026-09）
  - 基础版 72 张地牌完整规则（CAR v7.4 口径）
  - 单机热座 2-6 人 / 人机对战（三档 AI：简单/普通/困难）
  - 局域网联机：主机权威 + 快照同步 + 断线重连 + 主机代打
  - 高清贴图素材（程序化生成）：牌面/米宝/计分板 + 放置动画
  - 规则引擎与 UI/AI/联机解耦，含 7 套自动化验证

路线图
  - 官方牌面贴图替换（assets/tiles 同名替换即可）
"""
    with open(os.path.join(RELEASE, "使用说明.txt"), "w", encoding="utf-8") as f:
        f.write(usage)
    with open(os.path.join(RELEASE, "版本说明.txt"), "w", encoding="utf-8") as f:
        f.write(note)


def check_compile() -> None:
    """全部源码语法校验（py_compile）。"""
    import py_compile
    count = 0
    for base, _dirs, files in os.walk(os.path.join(ROOT, "game")):
        if "__pycache__" in base:
            continue
        for f in files:
            if f.endswith(".py"):
                py_compile.compile(os.path.join(base, f), doraise=True)
                count += 1
    for f in os.listdir(ROOT):
        if f.endswith(".py"):
            py_compile.compile(os.path.join(ROOT, f), doraise=True)
            count += 1
    print("语法校验 %d 个源文件通过" % count)


def run_release_gate() -> None:
    """发布门禁：语法 → 牌面校验+随机对局 → UI 全流程。任一失败即中止。"""
    check_compile()
    print("[门禁] 牌面校验 + 随机对局（verify_v1 6 局）……")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "verify_v1.py"),
                        "6"], cwd=ROOT)
    if r.returncode != 0:
        sys.exit("发布门禁失败：verify_v1 未通过，中止构建")
    print("[门禁] UI 全流程（verify_ui，会短暂弹出游戏窗口）……")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "verify_ui.py")],
                       cwd=ROOT)
    if r.returncode != 0:
        sys.exit("发布门禁失败：verify_ui 未通过，中止构建")
    print("[门禁] 全部通过")


def make_zip() -> str:
    """便携版 zip：EXE + 说明文档。"""
    import zipfile
    zpath = os.path.join(RELEASE, "卡卡颂_v%s_win64_便携版.zip" % VERSION)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(RELEASE)):
            if f.endswith(".zip"):
                continue
            z.write(os.path.join(RELEASE, f), arcname=f)
    return zpath


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest() -> dict:
    """release/ 全部产物生成 SHA256 清单（不含清单自身）。返回 {文件名: 哈希}。"""
    sums = {}
    for f in sorted(os.listdir(RELEASE)):
        p = os.path.join(RELEASE, f)
        if not os.path.isfile(p) or f == MANIFEST:
            continue
        sums[f] = _sha256(p)
    lines = ["# 卡卡颂 v%s 产物完整性清单（SHA256）" % VERSION,
             "# 校验：certutil -hashfile <文件> SHA256",
             ""]
    lines += ["%s  %s" % (digest, name)
              for name, digest in sorted(sums.items())]
    with open(os.path.join(RELEASE, MANIFEST), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("SHA256 清单：release/%s（%d 个文件）" % (MANIFEST, len(sums)))
    return sums


def log_release(sums: dict) -> None:
    """docs/发布记录.md 追加本次发布条目（自动建档）。"""
    path = os.path.join(DOCS, "发布记录.md")
    today = datetime.date.today().isoformat()
    if not os.path.exists(path):
        header = ("# 卡卡颂 发布记录\n\n"
                  "由 build_release.py 每次发布自动登记。\n\n")
    else:
        header = ""
    rows = []
    for name, digest in sorted(sums.items()):
        size = os.path.getsize(os.path.join(RELEASE, name))
        rows.append("| %s | %.1f MB | %s… |"
                    % (name, size / 1e6, digest[:16]))
    entry = ("## v%s（%s）\n\n"
             "发布格式：便携 zip（NSIS/Inno Setup 工具链不可用，安装包暂缓；"
             "SHA256 清单 + 本记录自动生成）。\n\n"
             "| 文件 | 大小 | SHA256（前 16 位） |\n"
             "|---|---|---|\n%s\n\n完整哈希见 release/SHA256SUMS.txt。\n\n"
             % (VERSION, today, "\n".join(rows)))
    text = ""
    if os.path.exists(path):
        text = io.open(path, encoding="utf-8").read()
    marker = "## v%s（" % VERSION
    if marker in text:
        # 同版本重复构建：替换原条目（哈希随构建时间变化）
        start = text.index(marker)
        end = text.find("\n## ", start)
        end = len(text) if end < 0 else end + 1
        text = text[:start] + entry + text[end:]
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        with open(path, "a", encoding="utf-8") as f:
            f.write(header + entry)
    print("发布记录：docs/发布记录.md 已登记 v%s" % VERSION)


def main() -> None:
    sys.path.insert(0, ROOT)
    skip_verify = "--skip-verify" in sys.argv

    if not skip_verify:
        run_release_gate()
    else:
        check_compile()
    print("[1/6] 验证门禁通过" if not skip_verify else "[1/6] 已跳过验证门禁")

    from game.art import ensure_assets
    ensure_assets()
    make_icon()
    os.makedirs(RELEASE, exist_ok=True)
    print("[2/6] 素材与图标就绪")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--onefile", "--windowed",
        "--name", EXE_NAME,
        "--icon", ICON,
        "--add-data", "assets;assets",
        "--hidden-import", "PIL._tkinter_finder",
        os.path.join(ROOT, "game", "main.py"),
    ]
    print("[3/6] PyInstaller 打包中（约 1-2 分钟）……")
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-4000:])
        print(r.stderr[-4000:])
        sys.exit(1)

    exe = os.path.join(ROOT, "dist", EXE_NAME + ".exe")
    if not os.path.exists(exe):
        print("构建失败：未找到 %s" % exe)
        sys.exit(1)
    shutil.copy(exe, os.path.join(RELEASE, EXE_NAME + ".exe"))
    write_docs()
    zpath = make_zip()
    size_mb = os.path.getsize(os.path.join(RELEASE, EXE_NAME + ".exe")) / 1e6
    print("[4/6] 便携包：%s" % os.path.basename(zpath))

    # 清理中间产物（dist 与 release 重复，spec 为临时配置）
    for d in ("build", "dist"):
        shutil.rmtree(os.path.join(ROOT, d), ignore_errors=True)
    for f in ("卡卡颂.spec", EXE_NAME + ".spec"):
        p = os.path.join(ROOT, f)
        if os.path.exists(p):
            os.remove(p)
    print("[5/6] 中间产物已清理")

    sums = write_manifest()
    log_release(sums)
    print("[6/6] 完成：release/%s v%s（%.1f MB）+ 便携包 + 文档 + SHA256 清单 + 发布记录" %
          (EXE_NAME, VERSION, size_mb))
    print("发布登记：docs/发布记录.md")


if __name__ == "__main__":
    main()
