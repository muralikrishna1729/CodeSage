import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import ChatPage from "./page";
import { makeStore } from "@/lib/store";
import { codesageApi } from "@/lib/services/codesageApi";
import { selectRepository } from "@/lib/features/repository/repositorySlice";
import type { Repository } from "@/components/dashboard/dashboard-types";

const mockRepos: Repository[] = [
  { repo_name: "owner/repo-a", points: 100 },
  { repo_name: "owner/repo-b", points: 200 },
];

const mockChatResponse = {
  answer: "This is the assistant answer.",
  source: "kb" as const,
};

type FetchMock = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

async function renderChatPage({
  initialRepositories = mockRepos,
  initialActiveRepository = null,
}: {
  initialRepositories?: Repository[];
  initialActiveRepository?: Repository | null;
} = {}) {
  const store = makeStore();

  // Seed the repository query cache using upsertQueryData because the
  // cache entry may not exist yet when using a fresh store.
  store.dispatch(
    codesageApi.util.upsertQueryData("getRepositories", undefined, initialRepositories)
  );

  // Select the initially active repository only when explicitly provided.
  // Do not automatically select the first repository — preserve the
  // default unselected-repository scenario.
  if (initialActiveRepository) {
    store.dispatch(selectRepository(initialActiveRepository.repo_name));
  }

  return render(
    <Provider store={store}>
      <ChatPage />
    </Provider>
  );
}

describe("ChatPage", () => {
  const fetchMock = vi.fn();

  // Chat response queue - each test configures its own sequence
  let chatResponseQueue: Array<() => Promise<Response>> = [];

  beforeEach(() => {
    fetchMock.mockReset();
    // Default queue with one successful chat response
    chatResponseQueue = [
      async () =>
        new Response(JSON.stringify(mockChatResponse), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    ];

    // Route-aware fetch mock:
    // - GET /api/codesage/repos → always return mockRepos (never touches queue)
    // - POST /api/codesage/chat → consume from chat response queue
    fetchMock.mockImplementation(async (input: RequestInfo) => {
      const request = new Request(input);
      const url = new URL(request.url);
      const method = request.method.toUpperCase();

      if (method === "GET" && url.pathname === "/api/codesage/repos") {
        // Repository GET always returns mockRepos, never touches chat queue
        return new Response(JSON.stringify(mockRepos), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }

      if (method === "POST" && url.pathname === "/api/codesage/chat") {
        // Chat POST consumes from the queue
        const handler = chatResponseQueue.shift();
        if (!handler) {
          throw new Error("Unexpected chat request - queue exhausted");
        }
        return handler();
      }

      throw new Error(`Unexpected request: ${method} ${url.pathname}`);
    });
    vi.spyOn(globalThis, "fetch").mockImplementation(fetchMock as unknown as FetchMock);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("Page rendering", () => {
    it("renders without crashing", async () => {
      await renderChatPage();
      const textarea = screen.getByPlaceholderText(/ask a question/i);
      expect(textarea).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /submit/i })).toBeInTheDocument();
      expect(screen.getByTestId("repository-select")).toBeInTheDocument();
    });

    it("disables submit button when input is empty", async () => {
      await renderChatPage({ initialActiveRepository: mockRepos[0] });
      const submitBtn = screen.getByRole("button", { name: /submit/i });
      expect(submitBtn).toBeDisabled();
    });

    it("enables submit button when input is not empty and repository selected", async () => {
      await renderChatPage({ initialActiveRepository: mockRepos[0] });
      const textarea = screen.getByPlaceholderText(/ask a question/i);
      fireEvent.change(textarea, { target: { value: "test question" } });
      const submitBtn = screen.getByRole("button", { name: /submit/i });
      expect(submitBtn).toBeEnabled();
    });
  });

  describe("Repository selection", () => {
    it("shows repository selector even when no repository is selected", async () => {
      await renderChatPage({ initialActiveRepository: null });
      expect(
        screen.getByText(/no repository selected/i)
      ).toBeInTheDocument();
      const select = screen.getByTestId("repository-select");
      expect(select).toBeInTheDocument();
    });

    it("selects a repository and enables input", () => {
      renderChatPage({ initialActiveRepository: null });
      const select = screen.getByTestId("repository-select");
      fireEvent.change(select, { target: { value: "owner/repo-a" } });
      const textarea = screen.getByPlaceholderText(/ask a question/i);
      fireEvent.change(textarea, { target: { value: "some question" } });
      const submitBtn = screen.getByRole("button", { name: /submit/i });
      expect(submitBtn).not.toBeDisabled();
      expect(screen.getByText(/active: owner\/repo-a/i)).toBeInTheDocument();
    });
  });

  describe("Empty question", () => {
    it("does not submit when question is empty", async () => {
      renderChatPage({ initialActiveRepository: mockRepos[0] });
      const submitBtn = screen.getByRole("button", { name: /submit/i });
      fireEvent.click(submitBtn);
      await waitFor(() => expect(fetchMock).not.toHaveBeenCalled());
    });
  });

  describe("Successful question submission", () => {
    it("submits a question and renders assistant response", async () => {
      renderChatPage({ initialActiveRepository: mockRepos[0] });
      const textarea = screen.getByPlaceholderText(/ask a question/i);
      fireEvent.change(textarea, { target: { value: "What is this?" } });
      const submitBtn = screen.getByRole("button", { name: /submit/i });
      fireEvent.click(submitBtn);

      await waitFor(() =>
        expect(screen.getByText("What is this?")).toBeInTheDocument()
      );
      await waitFor(() =>
        expect(screen.getByText("This is the assistant answer.")).toBeInTheDocument()
      );
    });

    it("renders the assistant answer", async () => {
      renderChatPage({ initialActiveRepository: mockRepos[0] });
      const textarea = screen.getByPlaceholderText(/ask a question/i);
      fireEvent.change(textarea, { target: { value: "Hello" } });
      fireEvent.click(screen.getByRole("button", { name: /submit/i }));
      await waitFor(() =>
        expect(screen.getByText("This is the assistant answer.")).toBeInTheDocument()
      );
    });
  });

  describe("Exact BFF request payload", () => {
    it("sends the exact request body to /api/codesage/chat", async () => {
      renderChatPage({ initialActiveRepository: mockRepos[0] });
      const textarea = screen.getByPlaceholderText(/ask a question/i);
      fireEvent.change(textarea, { target: { value: "How do I build?" } });
      fireEvent.click(screen.getByRole("button", { name: /submit/i }));

      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      const [url, options] = fetchMock.mock.calls[0];
      expect(url).toBe("/api/codesage/chat");
      expect(options.method).toBe("POST");
      expect(options.headers["Content-Type"]).toBe("application/json");
      const body = JSON.parse(options.body as string);
      expect(body).toEqual({
        question: "How do I build?",
        repo_name: "owner/repo-a",
        history: [],
      });
    });
  });

  describe("Correct repository name in request", () => {
    it("uses the selected repository name in the request", async () => {
      renderChatPage({ initialActiveRepository: mockRepos[1] });
      const textarea = screen.getByPlaceholderText(/ask a question/i);
      fireEvent.change(textarea, { target: { value: "Question for repo-b" } });
      fireEvent.click(screen.getByRole("button", { name: /submit/i }));
      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
      expect(body.repo_name).toBe("owner/repo-b");
    });
  });

  describe("Previous conversation history", () => {
    it("includes previous conversation history in the request", async () => {
      renderChatPage({ initialActiveRepository: mockRepos[0] });
      const textarea = screen.getByPlaceholderText(/ask a question/i);
      const submitBtn = screen.getByRole("button", { name: /submit/i });

      // First message
      fireEvent.change(textarea, { target: { value: "First question" } });
      fireEvent.click(submitBtn);
      await waitFor(() =>
        expect(screen.getByText("This is the assistant answer.")).toBeInTheDocument()
      );

      // Second message
      fireEvent.change(textarea, { target: { value: "Second question" } });
      fireEvent.click(submitBtn);
      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

      const secondBody = JSON.parse(fetchMock.mock.calls[1][1].body as string);
      expect(secondBody.history).toEqual([
        { role: "user", content: "First question" },
        { role: "assistant", content: "This is the assistant answer." },
      ]);
    });
  });

  describe("Source category rendering", () => {
    it("renders the source category of the assistant answer", async () => {
      renderChatPage({ initialActiveRepository: mockRepos[0] });
      const textarea = screen.getByPlaceholderText(/ask a question/i);
      fireEvent.change(textarea, { target: { value: "What is the source?" } });
      fireEvent.click(screen.getByRole("button", { name: /submit/i }));
      await waitFor(() =>
        expect(screen.getByText(/answer source: kb/i)).toBeInTheDocument()
      );
    });
  });

  describe("Loading and duplicate-submission prevention", () => {
    it("disables input while a request is in flight and prevents duplicates", async () => {
      let resolveFetch: (value: Response) => void = () => {};
      const deferred = new Promise<Response>((res) => {
        resolveFetch = res;
      });
      fetchMock.mockReturnValue(deferred);

      renderChatPage({ initialActiveRepository: mockRepos[0] });
      const textarea = screen.getByPlaceholderText(/ask a question/i);
      fireEvent.change(textarea, { target: { value: "Loading test" } });
      const submitBtn = screen.getByRole("button", { name: /submit/i });
      fireEvent.click(submitBtn);

      // While loading, submit should be disabled
      await waitFor(() => expect(submitBtn).toBeDisabled());

      // Attempting to submit again while loading should not create a second call
      fireEvent.click(submitBtn);
      expect(fetchMock).toHaveBeenCalledTimes(1);

      resolveFetch(
        new Response(JSON.stringify(mockChatResponse), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      );
      await waitFor(() =>
        expect(screen.getByText("This is the assistant answer.")).toBeInTheDocument()
      );
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
  });

  describe("API error", () => {
    it("shows an error message when the BFF returns an error", async () => {
      fetchMock.mockResolvedValue(
        new Response(JSON.stringify({ error: "bad request" }), {
          status: 400,
          statusText: "Bad Request",
        })
      );
      await renderChatPage({ initialActiveRepository: mockRepos[0] });
      const textarea = screen.getByPlaceholderText(/ask a question/i);
      fireEvent.change(textarea, { target: { value: "Bad question" } });
      fireEvent.click(screen.getByRole("button", { name: /submit/i }));
      await waitFor(
        expect(screen.getByRole("alert")).toBeInTheDocument()
      );
    });
  });

  describe("Network error", () => {
    it("shows an error message when the network request fails", async () => {
      // Only reject the chat POST, not the repository GET
      fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
      await renderChatPage({ initialActiveRepository: mockRepos[0] });
      const textarea = screen.getByPlaceholderText(/ask a question/i);
      fireEvent.change(textarea, { target: { value: "Network question" } });
      fireEvent.click(screen.getByRole("button", { name: /submit/i }));
      // Use findByRole for automatic waiting - it will retry until the element appears
      const alert = await screen.findByRole("alert", { selector: undefined });
      expect(alert).toBeInTheDocument();
    });
  });

  describe("Enter and Shift+Enter", () => {
    it("submits on Enter (without Shift)", async () => {
      await renderChatPage({ initialActiveRepository: mockRepos[0] });
      const textarea = screen.getByPlaceholderText(/ask a question/i);
      fireEvent.change(textarea, { target: { value: "Enter submit" } });
      fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });
      // Wait for the assistant answer to appear in the message list
      await waitFor(() =>
        expect(screen.getByText(/Enter submit/)).toBeInTheDocument()
      );
      // Verify exactly one POST /api/codesage/chat was made
      const chatRequests = fetchMock.mock.calls.filter(
        ([input]) => new Request(input).method === "POST" && new Request(input).url.includes("/api/codesage/chat")
      );
      expect(chatRequests).toHaveLength(1);
      // Verify the request body contains the question and repository
      const [, init] = chatRequests[0];
      const body = JSON.parse(init.body);
      expect(body.question).toBe("Enter submit");
      expect(body.repo_name).toBe(mockRepos[0].repo_name);
    });

    it("inserts a newline on Shift+Enter without submitting", async () => {
      await renderChatPage({ initialActiveRepository: mockRepos[0] });
      const textarea = screen.getByPlaceholderText(/ask a question/i);
      fireEvent.change(textarea, { target: { value: "line one" } });
      fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });
      // Shift+Enter should insert a newline without submitting
      expect(textarea).toHaveValue("line one\n");
      // No assistant answer should appear since no submit occurred
      // Use queryByRole for negative DOM assertions - returns null if not found
      const alert = screen.queryByRole("alert", { selector: undefined });
      expect(alert).not.toBeInTheDocument();
    });
  });

  describe("Retry without duplicate user messages", () => {
    it("retries after an error without duplicating the user message", async () => {
      fetchMock
        .mockRejectedValueOnce(new TypeError("Failed to fetch"))
        .mockResolvedValue(
          new Response(JSON.stringify(mockChatResponse), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
        );

      await renderChatPage({ initialActiveRepository: mockRepos[0] });
      const textarea = screen.getByPlaceholderText(/ask a question/i);
      fireEvent.change(textarea, { target: { value: "Retry question" } });
      const submitBtn = screen.getByRole("button", { name: /submit/i });

      // First attempt fails
      fireEvent.click(submitBtn);
      await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

      // Clear error by clicking submit again (retry)
      fireEvent.click(submitBtn);
      await waitFor(() =>
        expect(screen.getByText("This is the assistant answer.")).toBeInTheDocument()
      );

      // The user message should appear exactly once
      const userMessages = screen.getAllByText("Retry question");
      expect(userMessages).toHaveLength(1);
    });
  });
});

