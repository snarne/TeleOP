import { Link } from "react-router-dom";
import { Empty } from "../components/ui";

export function NotFound() {
  return (
    <div className="page">
      <Empty title="This page doesn't exist" action={<Link className="btn btn-primary btn-md" to="/">Go to Operate</Link>}>
        Use the navigation on the left to find what you need.
      </Empty>
    </div>
  );
}
