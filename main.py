"""Сначала: python -m alembic upgrade head. Сервер: python -m uvicorn main:app --reload."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Response, FastAPI, HTTPException, Path as PathParameter
from sqlalchemy import URL, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db import get_session
from models import Task
from schemas import TaskCreate, TaskResponse, TaskUpdate

TaskId = Annotated[int, PathParameter(gt=0)]


def create_app(database_path: Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        url = URL.create("sqlite+aiosqlite", database=str(app.state.database_path))
        engine = create_async_engine(url)
        app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            # Схему готовим заранее командой python -m alembic upgrade head.
            yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title="Список задач",
        description="Учебный JSON API на FastAPI, Pydantic и SQLAlchemy.",
        lifespan=lifespan,
    )
    app.state.database_path = (
        database_path if database_path is not None else Path(__file__).with_name("tasks.sqlite3")
    )

    @app.get("/tasks", response_model=list[TaskResponse], tags=["Задачи"])
    async def task_list(
        session: AsyncSession = Depends(get_session),
        done: bool | None = None,
    ):
        """Все задачи или выборка по признаку выполнения. Новые задачи сверху."""
        statement = select(Task).order_by(Task.id.desc())
        if done is not None:
            statement = statement.where(Task.done == done)
        result = await session.execute(statement)
        return result.scalars().all()

    @app.post("/tasks", response_model=TaskResponse, status_code=201, tags=["Задачи"])
    async def task_create(
        task: TaskCreate,
        session: AsyncSession = Depends(get_session),
    ):
        """Создать задачу. Название содержит от 1 до 120 символов."""
        new_task = Task(title=task.title)
        session.add(new_task)
        await session.commit()
        await session.refresh(new_task)
        return new_task

    @app.patch("/tasks/{task_id}", response_model=TaskResponse, tags=["Задачи"])
    async def task_update(
        task_id: TaskId,
        task: TaskUpdate,
        session: AsyncSession = Depends(get_session),
    ):
        """Явно задать done. Вернуть 404, если задачи нет."""
        saved_task = await session.get(Task, task_id)
        if saved_task is None:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        # Явно задаём состояние. Повторный PATCH не переключит его обратно.
        saved_task.done = task.done
        await session.commit()
        await session.refresh(saved_task)
        return saved_task


    @app.get("/tasks/{task_id}", response_model=TaskResponse, tags=["Задачи"])
    async def get_task(
        task_id: TaskId, session: AsyncSession = Depends(get_session)
    ):
        task = await session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @app.delete("/tasks/{task_id}", status_code=204, tags=["Задачи"])
    async def delete_task(
        task_id: TaskId, session: AsyncSession = Depends(get_session)
    ):
        task = await session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        await session.delete(task)
        await session.commit()
        return Response(status_code=204)

    return app

app = create_app()
