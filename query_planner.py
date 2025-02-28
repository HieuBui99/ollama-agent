import json
import re
import os
from pprint import pprint
from typing import List, Literal

import instructor
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field

load_dotenv()


client = OpenAI(
    base_url = os.getenv('OLLAMA_URL'),
    api_key='ollama', 
)

client = instructor.from_openai(client, mode=instructor.Mode.JSON)


import enum
import asyncio

class QueryType(str, enum.Enum):
    """
    Enumeration representing the types of queries that can be asked to a question answer system.
    """

    # When i call it anything beyond 'merge multiple responses' the accuracy drops significantly.
    SINGLE_QUESTION = "SINGLE"
    MERGE_MULTIPLE_RESPONSES = "MERGE_MULTIPLE_RESPONSES"


class ComputeQuery(BaseModel):
    """
    Models a computation of a query, assume this can be some RAG system like llamaindex
    """

    query: str
    response: str = "..."


class MergedResponses(BaseModel):
    """
    Models a merged response of multiple queries.
    Currently we just concatinate them but we can do much more complex things.
    """

    responses: list[ComputeQuery]


class Query(BaseModel):
    """
    Class representing a single question in a question answer subquery.
    Can be either a single question or a multi question merge.
    """

    id: int = Field(..., description="Unique id of the query")
    question: str = Field(
        ...,
        description="Question we are asking using a question answer system, if we are asking multiple questions, this question is asked by also providing the answers to the sub questions",
    )
    dependancies: list[int] = Field(
        default_factory=list,
        description="List of sub questions that need to be answered before we can ask the question. Use a subquery when anything may be unknown, and we need to ask multiple questions to get the answer. Dependences must only be other queries.",
    )
    node_type: QueryType = Field(
        default=QueryType.SINGLE_QUESTION,
        description="Type of question we are asking, either a single question or a multi question merge when there are multiple questions",
    )

    async def execute(self, dependency_func):
        print("Executing", self.question)
        print("Executing with", len(self.dependancies), "dependancies")

        if self.node_type == QueryType.SINGLE_QUESTION:
            resp = ComputeQuery(
                query=self.question,
            )
            await asyncio.sleep(1)
            pprint(resp.model_dump())
            return resp

        sub_queries = dependency_func(self.dependancies)
        computed_queries = await asyncio.gather(
            *[q.execute(dependency_func=dependency_func) for q in sub_queries]
        )
        sub_answers = MergedResponses(responses=computed_queries)
        merged_query = f"{self.question}\nContext: {sub_answers.model_dump_json()}"
        resp = ComputeQuery(
            query=merged_query,
        )
        await asyncio.sleep(2)
        pprint(resp.model_dump())
        return resp


class QueryPlan(BaseModel):
    """
    Container class representing a tree of questions to ask a question answer system.
    and its dependencies. Make sure every question is in the tree, and every question is asked only once.
    """

    query_graph: list[Query] = Field(
        ..., description="The original question we are asking"
    )

    async def execute(self):
        # this should be done with a topological sort, but this is easier to understand
        original_question = self.query_graph[-1]
        print(f"Executing query plan from `{original_question.question}`")
        return await original_question.execute(dependency_func=self.dependencies)

    def dependencies(self, idz: list[int]) -> list[Query]:
        """
        Returns the dependencies of the query with the given id.
        """ 
        return [q for q in self.query_graph if q.id in idz]


Query.model_rebuild()
QueryPlan.model_rebuild()


def query_planner(question: str, plan=False) -> QueryPlan:

    messages = [
        {
            "role": "system",
            "content": "You are a world class query planning algorithm capable of breaking apart questions into its depenencies queries such that the answers can be used to inform the parent question. Do not answer the questions, simply provide correct compute graph with good specific questions to ask and relevant dependencies. Before you call the function, think step by step to get a better understanding the problem.",
        },
        {
            "role": "user",
            "content": f"Consider: {question}\nGenerate the correct query plan.",
        },
    ]

    if plan:
        messages.append(
            {
                "role": "assistant",
                "content": "Lets think step by step to find correct set of queries and its dependencies and not make any assuptions on what is known.",
            },
        )
        completion = client.chat.completions.create(
            model="deepseek-r1:14b", temperature=0, messages=messages, max_tokens=1000
        )

        messages.append(completion["choices"][0]["message"])

        messages.append(
            {
                "role": "user",
                "content": "Using that information produce the complete and correct query plan.",
            }
        )

    root = client.chat.completions.create(
        model="TonAI:chatbot",
        temperature=0,
        response_model=QueryPlan,
        messages=messages,
        max_tokens=1000,
    )
    return root


plan = query_planner(
    "What is the difference in populations of Canada and the Jason's home country?",
    plan=False,
)
pprint(plan.model_dump())

asyncio.run(plan.execute())