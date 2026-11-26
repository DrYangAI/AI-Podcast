"""用量记录 - 每次成功的 AI 调用记一行原始用量(不存费用)。

费用在汇总时用【当前价格表】实时算,所以价格表是唯一真相源:改了价格表,
历史估算立刻跟着纠正。只记成功调用(失败不计费),本地 VoxCPM 等免费项 price=0。

一行 = 一个计费组件:
- 图片:unit="image", quantity=张数
- TTS :unit="char",  quantity=合成字数
- 文本:拆两行,unit="token_in"/"token_out", quantity=对应 token 数
"""

import uuid
from datetime import datetime

from sqlalchemy import String, Float, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    # 项目可空:有些调用(如批量提示词)也挂在项目下,但保留 null 容错
    project_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    provider_type: Mapped[str] = mapped_column(String(20), nullable=False)   # image/tts/text
    provider_key: Mapped[str] = mapped_column(String(50), nullable=False)    # doubao_seedream/deepseek/...
    model_id: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    unit: Mapped[str] = mapped_column(String(20), nullable=False)            # image/char/token_in/token_out
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # 冗余一个人类可读标签,方便前端展示(如"段落配图""文章生成")
    label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
